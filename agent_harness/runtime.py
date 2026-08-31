"""Shared runtime preparation and execution helpers."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_harness.budget import Budget
from agent_harness.hooks import Hooks
from agent_harness.loops import registry as loop_registry
from agent_harness.mcp_client import McpManager, McpServerSpec
from agent_harness.network import _extract_domain
from agent_harness.permissions import PermissionDecision, Permissions
from agent_harness.providers import registry as provider_registry
from agent_harness.runtime_callbacks import _NullTracer, make_callbacks
from agent_harness.session import Session
from agent_harness.skills import load_skills
from agent_harness.tools import (
    ToolRuntimeContext,
    build_tool_registry,
    discover_tools,
    generate_schema,
)
from agent_harness.trace import Tracer
from agent_harness.types import (
    AgentConfig,
    LoopCallbacks,
    Message,
    OnPlanApproval,
    OutputSink,
    Response,
    ToolCall,
)

PermissionPromptFn = Callable[[ToolCall], PermissionDecision | bool]
DomainPromptFn = Callable[[str], bool]

logger = logging.getLogger(__name__)


def _build_mcp_tool_callable(manager: McpManager, server: str, name: str) -> Callable[..., str]:
    def _call(**kwargs: Any) -> str:
        return manager.call_tool(server, name, kwargs)

    _call.__name__ = name
    return _call


_BROWSER_NAV_TOOL_NAMES = {"browser_navigate", "browser_click"}
_PAGE_URL_LINE_PATTERN = re.compile(r"^- Page URL: (\S+)", re.MULTILINE)


def _extract_domain_from_snapshot(text: str) -> str | None:
    """Extract the current page's domain from a Playwright MCP action result.

    Playwright MCP's `browser_navigate`/`browser_click`/`browser_snapshot`
    results all include a "- Page URL: <url>" line reporting where the
    browser actually ended up — verified directly against a real running
    `@playwright/mcp` server (2026-08-31), not assumed. Only this specific
    line is matched, not any URL elsewhere in the result text (e.g. inside
    the "Ran Playwright code" JS snippet, which can differ from the real
    destination after a redirect).

    Args:
        text: Raw text result from a Playwright MCP tool call.

    Returns:
        The domain from the Page URL line, or `None` if the line isn't present.
    """
    match = _PAGE_URL_LINE_PATTERN.search(text)
    return _extract_domain(match.group(1)) if match else None


def _wrap_browser_nav_tool(manager: McpManager, server: str, name: str, hooks: Hooks) -> Callable[..., str]:
    """Wrap a Playwright MCP navigation tool with a post-call domain gate.

    `browser_click`'s arguments carry an opaque element reference, not a
    URL, so the harness can't know the destination before the call runs —
    a click could land on any domain. Checking the *result* instead closes
    that gap: after the call completes, the resulting page's domain is run
    through a synthetic `browser_navigate` `ToolCall` against the existing
    hook chain, reusing `network_exfiltration_blocker`'s
    allowlist/prompt/persistence exactly (not a second mechanism) — the
    same check `browser_navigate`'s own `url` argument already goes
    through today. Denied → the browser is navigated back and the agent
    gets a message instead of the unapproved page's content.
    `browser_navigate` is wrapped too, not just `browser_click` — its own
    pre-call check only validates the URL the agent wrote, not where the
    page actually ends up, so this also catches a redirect the pre-call
    check alone can't see.

    Args:
        manager: The connected MCP manager to call through.
        server: Name of the MCP server this tool belongs to — callers only
            use this wrapper for the server actually named `playwright`.
        name: The tool's name (`browser_navigate` or `browser_click`).
        hooks: This run's hook chain, reused rather than duplicated.

    Returns:
        A tool-registry callable with the same call shape as a plain MCP passthrough.
    """

    def _call(**kwargs: Any) -> str:
        result = manager.call_tool(server, name, kwargs)
        domain = _extract_domain_from_snapshot(result)
        if domain is None:
            return result
        synthetic = ToolCall(id="", name="browser_navigate", arguments={"url": f"https://{domain}"})
        if hooks.run_before_tool(synthetic) is None:
            manager.call_tool(server, "browser_navigate_back", {})
            return f"Navigation to {domain} was not approved and has been reverted."
        return result

    _call.__name__ = name
    return _call


def _connect_mcp_servers(config: AgentConfig) -> tuple[McpManager | None, list[McpServerSpec]]:
    """Start any configured MCP servers, without merging their tools yet.

    Split from `_merge_mcp_tools` so a built-in tool (e.g.
    `read_live_page_content`) can be constructed with a live reference to
    the manager — via `ToolRuntimeContext.mcp_manager` — before
    `build_tool_registry` runs, which happens between this call and the
    merge step in `prepare_runtime`.

    Args:
        config: Loaded agent configuration. `mcp_servers` (if any) drives
            which servers to connect to.

    Returns:
        The started manager (`None` if no servers are configured) and the
        specs used to build it — the merge step needs the specs again for
        each server's optional `tools` allow-list.
    """
    if not config.mcp_servers:
        return None, []
    specs = [McpServerSpec(**spec) for spec in config.mcp_servers]
    manager = McpManager(specs)
    manager.start()
    return manager, specs


def _merge_mcp_tools(
    config: AgentConfig,
    manager: McpManager | None,
    specs: list[McpServerSpec],
    tool_registry: dict[str, Callable[..., str]],
    hooks: Hooks,
) -> list[dict[str, Any]]:
    """Merge an already-connected MCP manager's tools into the registry.

    Args:
        config: Loaded agent configuration. `tools` is what this agent
            actually exposes to the model — the collision check is against
            this, not the full tool registry, since an unexposed built-in
            (present in the registry but never offered to the model) isn't
            really competing with an MCP tool of the same name.
        manager: The manager `_connect_mcp_servers` already started, or
            `None` if this agent has no MCP servers configured.
        specs: The same specs `_connect_mcp_servers` built the manager
            from — used here for each server's optional `tools` allow-list.
        tool_registry: Registry to merge discovered MCP tools into, mutated
            in place. A tool whose name is already exposed via `config.tools`,
            or already claimed by an earlier MCP server in this same merge,
            is skipped — not overwritten. A server that declares its own
            `tools` allow-list only ever contributes tools on that list; a
            server with no allow-list (the default) still exposes
            everything it reports, unchanged from before this field existed.
        hooks: This run's hook chain — threaded into `browser_navigate`/
            `browser_click` from a server named `playwright` so they get
            the post-call domain-revert wrapper instead of a plain
            passthrough (see `_wrap_browser_nav_tool`). Every other MCP
            tool, on any server, is unaffected.

    Returns:
        Schema dicts for every tool that was actually merged in.
    """
    if manager is None:
        return []
    allowlist_by_server = {spec.name: set(spec.tools) for spec in specs if spec.tools is not None}
    exposed_names = set(config.tools)
    claimed_by_mcp: set[str] = set()
    schemas: list[dict[str, Any]] = []
    for tool in manager.list_tools():
        name = tool["name"]
        server = tool["server"]
        allowlist = allowlist_by_server.get(server)
        if allowlist is not None and name not in allowlist:
            continue
        if name in exposed_names or name in claimed_by_mcp:
            logger.warning(
                "MCP tool '%s' from server '%s' skipped — name collision", name, server,
            )
            continue
        if server == "playwright" and name in _BROWSER_NAV_TOOL_NAMES:
            tool_registry[name] = _wrap_browser_nav_tool(manager, server, name, hooks)
        else:
            tool_registry[name] = _build_mcp_tool_callable(manager, server, name)
        claimed_by_mcp.add(name)
        schemas.append({"name": name, "description": tool["description"], "input_schema": tool["input_schema"]})
    return schemas


@dataclass
class PreparedRuntime:
    """Prepared execution state for one configured agent run.

    Attributes:
        config: Loaded agent configuration.
        chat_fn: Provider chat function for the configured provider.
        loop_fn: Selected loop implementation.
        tool_registry: Per-run tool registry with built-ins bound to runtime context.
        tool_schemas: JSON schemas for tools enabled in the agent config.
        callbacks: Loop callbacks for display, tool execution, and budget handling.
        permissions: Permission manager for the current run.
        tracer: Structured trace sink, or a no-op tracer when tracing is disabled.
        budget: Turn/cost tracker for this run.
        mcp_manager: Connections to this run's configured MCP servers, or
            None if the agent has none configured.
        tmp_dir: This run's isolated scratch directory, unique per
            `prepare_runtime` call so concurrent runs never collide.
    """

    config: AgentConfig
    chat_fn: Callable[..., Response]
    loop_fn: Callable[..., str]
    tool_registry: dict[str, Callable[..., str]]
    tool_schemas: list[dict[str, Any]]
    callbacks: LoopCallbacks
    permissions: Permissions
    tracer: Tracer | _NullTracer
    budget: Budget
    mcp_manager: McpManager | None = None
    tmp_dir: str = ""

    def init_messages(
        self,
        session: Session | None = None,
        existing_messages: list[Message] | None = None,
    ) -> list[Message]:
        """Load a session's history or build a fresh message list for this agent.

        Args:
            session: Optional already-resolved session to continue.
            existing_messages: Existing conversation state to continue, such as a handoff.

        Returns:
            Message list ready to pass into the configured loop.
        """
        if existing_messages is not None:
            if existing_messages:
                return existing_messages
            return [Message(role="system", content=build_system_prompt(self.config))]
        messages = session.messages if session is not None else []
        if not messages:
            messages = [Message(role="system", content=build_system_prompt(self.config))]
        return messages

    def run_messages(self, messages: list[Message], prompt: str | None = None) -> str:
        """Run the configured loop against a message list.

        Args:
            messages: Conversation history to mutate in place.
            prompt: Optional user prompt to append before running.

        Returns:
            Final assistant text returned by the loop.
        """
        if prompt is not None:
            self.tracer.record("user_prompt", content=prompt)
            messages.append(Message(role="user", content=prompt))
        return self.loop_fn(self.chat_fn, messages, self.tool_schemas, self.config, self.callbacks)

    def finalize(self) -> None:
        """Persist runtime state that should survive the current process.

        Writes persistent permission approvals if they changed, and closes
        any MCP server connections this run opened.
        """
        self.permissions.save()
        if self.mcp_manager is not None:
            self.mcp_manager.close()


def build_system_prompt(config: AgentConfig) -> str:
    """Combine instructions, tools guidance, and skills into a system prompt.

    Args:
        config: Agent configuration containing instructions, optional tools guidance,
            and the agent directory used to discover local skills.

    Returns:
        Final system prompt text in the order: instructions, tools guidance, skills.
    """
    prompt = config.instructions
    if config.tools_guidance:
        prompt += "\n\n" + config.tools_guidance
    skills_content = load_skills("skills", f"{config.agent_dir}/skills")
    if skills_content:
        prompt += "\n\n" + skills_content
    return prompt


def trace_context(tracer: Tracer | _NullTracer, config: AgentConfig) -> None:
    """Record which files were loaded into the agent context.

    Args:
        tracer: Trace sink for structured events.
        config: Agent configuration used to locate prompt source files.
    """
    files: list[str] = [
        f"{config.agent_dir}/config.yaml",
        f"{config.agent_dir}/instructions.md",
    ]
    tools_md = f"{config.agent_dir}/tools.md"
    if Path(tools_md).exists():
        files.append(tools_md)
    for skills_dir in ["skills", f"{config.agent_dir}/skills"]:
        skills_path = Path(skills_dir)
        if skills_path.is_dir():
            for skill_dir in sorted(skills_path.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    files.append(str(skill_file))
    tracer.record("context_loaded", agent=config.name, files=files, tools=config.tools, loop=config.loop)


def validate_config(
    config: AgentConfig,
    tool_registry: dict[str, Callable[..., str]] | None = None,
) -> None:
    """Validate config references against available providers, tools, and loops.

    Args:
        config: Loaded agent configuration to validate.
        tool_registry: Optional tool registry to validate against. If omitted,
            validation uses the built-in registry only.

    Raises:
        ValueError: If provider, tool, loop, or max_turns is invalid.
    """
    active_registry = tool_registry or build_tool_registry()
    if config.provider not in provider_registry:
        raise ValueError(f"Unknown provider: {config.provider}")
    for tool_name in config.tools:
        if tool_name not in active_registry:
            raise ValueError(f"Unknown tool: {tool_name}")
    if config.loop not in loop_registry:
        raise ValueError(f"Unknown loop: {config.loop}")
    if config.max_turns < 1:
        raise ValueError(f"max_turns must be > 0, got {config.max_turns}")
    if config.stream and config.provider not in ("anthropic", "openai"):
        raise ValueError(f"stream is not supported for provider '{config.provider}'")
    if "thinking" in config.provider_kwargs and config.provider != "anthropic":
        raise ValueError(f"thinking is only supported for the anthropic provider, got '{config.provider}'")
    if config.completion_check and config.loop not in ("reflection", "ralph", "eval_optimize"):
        logger.warning(
            "completion_check is set but loop '%s' does not honor it "
            "(only reflection/ralph/eval_optimize do) — it will be silently ignored",
            config.loop,
        )


def deny_permission(_tool_call: ToolCall) -> PermissionDecision:
    """Deterministic denial callback for non-interactive runs.

    Args:
        _tool_call: Tool call requesting approval.

    Returns:
        A denial decision, used by delegated runs that cannot prompt.
    """
    return PermissionDecision.deny()


def prepare_runtime(
    config: AgentConfig,
    *,
    permission_prompt_fn: PermissionPromptFn,
    domain_prompt_fn: DomainPromptFn | None = None,
    plan_prompt_fn: OnPlanApproval | None = None,
    show_output: bool = True,
    trace_enabled: bool = True,
    output_sink: OutputSink | None = None,
    is_cancelled_fn: Callable[[], bool] | None = None,
) -> PreparedRuntime:
    """Prepare everything needed to execute an agent consistently.

    Args:
        config: Loaded agent configuration.
        permission_prompt_fn: Callback used when a tool call needs approval.
        domain_prompt_fn: Optional callback used by the network blocker to approve domains.
        plan_prompt_fn: Optional callback used by `plan_execute` to approve a
            generated plan before it executes. Inert if omitted.
        show_output: Whether response/tool panels should be rendered to the console.
        trace_enabled: Whether structured trace files should be written.
        output_sink: Optional hooks for a non-console driver (e.g. an API
            server) to receive run events. Fires alongside, not instead of,
            the console display — inert (`None`) leaves CLI behavior unchanged.
        is_cancelled_fn: Optional `() -> bool`, checked at each turn/stream
            checkpoint to stop a run gracefully. Inert (`None`) leaves
            behavior unchanged. The CLI reads a mutable flag it resets
            before each turn (one `PreparedRuntime` is reused across a
            REPL's turns); the API sources it directly from its per-run
            registry state.

    Returns:
        Prepared runtime object that can initialize messages, run the loop, and persist
        permission state at the end of the session.

    Note:
        Each call gets its own subfolder under `{agent_dir}/tmp/` so concurrent
        runs of the same agent never clobber each other's scratch output.
        Old run subfolders are not cleaned up — age-based cleanup would need a
        threshold that can't misfire against a genuinely slow still-running
        process, and there's no evidence yet that unbounded `tmp/` growth is
        a real problem worth that risk.
    """
    run_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(config.agent_dir) / "tmp" / run_id
    tmp_dir.mkdir(parents=True, exist_ok=True)

    mcp_manager, mcp_specs = _connect_mcp_servers(config)
    tool_context = ToolRuntimeContext(
        memory_dir=f"{config.agent_dir}/memory",
        tool_timeout=config.tool_timeout,
        executor=config.executor,
        mcp_manager=mcp_manager,
    )
    tool_registry = build_tool_registry(tool_context)
    discover_tools("tools", base_registry=tool_registry)
    validate_config(config, tool_registry)

    tracer: Tracer | _NullTracer
    if trace_enabled:
        tracer = Tracer(f"{config.agent_dir}/logs")
        trace_context(tracer, config)
    else:
        tracer = _NullTracer()

    hooks = Hooks(
        config.hooks,
        domain_prompt_fn=domain_prompt_fn,
        agent_dir=config.agent_dir,
        workspace_root=str(Path.cwd()),
    )
    permissions = Permissions(
        config.permissions,
        prompt_fn=permission_prompt_fn,
        persist_path=f"{config.agent_dir}/.permissions.yaml",
    )
    permissions.load()
    budget = Budget(config)
    callbacks = make_callbacks(
        budget,
        hooks,
        permissions,
        tracer,
        tool_registry,
        config.max_output_chars,
        show_output,
        stream=config.stream,
        show_thinking=config.show_thinking,
        plan_prompt_fn=plan_prompt_fn,
        tmp_dir=str(tmp_dir),
        output_sink=output_sink,
        is_cancelled=is_cancelled_fn,
    )
    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    mcp_tool_schemas = _merge_mcp_tools(config, mcp_manager, mcp_specs, tool_registry, hooks)
    tool_schemas = [generate_schema(tool_registry[name]) for name in config.tools] + mcp_tool_schemas
    return PreparedRuntime(
        config=config,
        chat_fn=chat_fn,
        loop_fn=loop_fn,
        tool_registry=tool_registry,
        tool_schemas=tool_schemas,
        callbacks=callbacks,
        permissions=permissions,
        tracer=tracer,
        budget=budget,
        mcp_manager=mcp_manager,
        tmp_dir=str(tmp_dir),
    )
