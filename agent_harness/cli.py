"""CLI composition root — wires everything together."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from agent_harness import config as config_loader
from agent_harness.budget import Budget
from agent_harness.display import (
    prompt_user,
    show_budget,
    show_response,
    show_tool_call,
    show_tool_result,
)
from agent_harness.hooks import Hooks
from agent_harness.log import setup_logging
from agent_harness.loops import registry as loop_registry
from agent_harness.permissions import Permissions
from agent_harness.providers import registry as provider_registry
from agent_harness.scaffold import create_agent
from agent_harness.session import load_session, save_session
from agent_harness.skills import load_skills
from agent_harness.tools import execute_tool, generate_schema
from agent_harness.tools import registry as tool_registry
from agent_harness.trace import Tracer
from agent_harness.types import AgentConfig, LoopCallbacks, Message, Response, ToolCall, ToolResult, Usage

_console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace with command, agent_dir, prompt, verbose.
    """
    parser = argparse.ArgumentParser(description="Agent Harness")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Run an agent")
    run_parser.add_argument("agent_dir", help="Path to agent folder")
    run_parser.add_argument("prompt", nargs="?", default=None, help="Single prompt")
    run_parser.add_argument("--session", default=None, help="Session name to save/resume")
    run_parser.add_argument("--verbose", action="store_true", help="Verbose output")
    run_parser.add_argument("--provider", default=None, help="Override provider")
    run_parser.add_argument("--model", default=None, help="Override model")
    run_parser.add_argument("--loop", default=None, help="Override loop pattern")
    run_parser.add_argument("--max-turns", type=int, default=None, help="Override max turns")
    run_parser.add_argument("--max-cost", type=float, default=None, help="Override max cost")
    run_parser.add_argument("--executor", default=None, help="Override code executor")
    run_parser.add_argument("--tool-timeout", type=int, default=None, help="Override tool timeout")
    run_parser.add_argument("--max-output-chars", type=int, default=None, help="Override max output chars")

    init_parser = sub.add_parser("init", help="Create a new agent")
    init_parser.add_argument("name", help="Agent name")

    return parser.parse_args(argv)


def validate_config(config: AgentConfig) -> None:
    """Validate config references against registries.

    Args:
        config: Loaded agent configuration.

    Raises:
        ValueError: If provider, tool, loop, or max_turns is invalid.
    """
    if config.provider not in provider_registry:
        raise ValueError(f"Unknown provider: {config.provider}")
    for tool_name in config.tools:
        if tool_name not in tool_registry:
            raise ValueError(f"Unknown tool: {tool_name}")
    if config.loop not in loop_registry:
        raise ValueError(f"Unknown loop: {config.loop}")
    if config.max_turns < 1:
        raise ValueError(f"max_turns must be > 0, got {config.max_turns}")


def _trace_context(tracer: Tracer, config: AgentConfig) -> None:
    """Record which files were loaded into the agent context.

    Args:
        tracer: Event tracer.
        config: Agent configuration.
    """
    files: list[str] = [
        f"{config.agent_dir}/config.yaml",
        f"{config.agent_dir}/instructions.md",
    ]
    tools_md = f"{config.agent_dir}/tools.md"
    if Path(tools_md).exists():
        files.append(tools_md)

    # Scan for loaded skills
    for skills_dir in ["skills", f"{config.agent_dir}/skills"]:
        skills_path = Path(skills_dir)
        if skills_path.is_dir():
            for skill_dir in sorted(skills_path.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    files.append(str(skill_file))

    tracer.record("context_loaded", agent=config.name, files=files, tools=config.tools, loop=config.loop)


def _build_system_prompt(config: AgentConfig) -> str:
    """Combine instructions, tools guidance, and skills into a system prompt.

    Args:
        config: Agent configuration.

    Returns:
        System prompt string.
    """
    prompt = config.instructions
    if config.tools_guidance:
        prompt += "\n\n" + config.tools_guidance
    skills_content = load_skills("skills", f"{config.agent_dir}/skills")
    if skills_content:
        prompt += "\n\n" + skills_content
    return prompt


def _permission_prompt(tool_call: ToolCall) -> bool:
    """Ask the user whether to allow a tool call.

    Args:
        tool_call: The tool call requesting approval.

    Returns:
        True if the user approves.
    """
    args_str = json.dumps(tool_call.arguments, indent=2)
    _console.print(f"[bold yellow]Tool:[/bold yellow] {tool_call.name}")
    _console.print(f"[bold yellow]Args:[/bold yellow] {args_str}")
    choice = _console.input("[a]llow once / allow for [s]ession / [d]eny? ").strip().lower()
    return choice in ("a", "s")


def _domain_prompt(domain: str) -> bool:
    """Ask the user whether to allow network access to a domain.

    Args:
        domain: The domain requesting access.

    Returns:
        True if the user approves.
    """
    choice = _console.input(
        f"[bold yellow]Allow network access to [cyan]{domain}[/cyan]?[/bold yellow] [y/n] "
    ).strip().lower()
    return choice in ("y", "yes")


def _make_callbacks(
    budget: Budget, hooks: Hooks, permissions: Permissions,
    tracer: Tracer, max_output_chars: int = 10_000,
) -> LoopCallbacks:
    """Create display callbacks with hooks, permissions, and tracing.

    Args:
        budget: Budget tracker.
        hooks: Safety hooks.
        permissions: Tool permissions.
        tracer: Structured event tracer.
        max_output_chars: Max tool output before truncation.

    Returns:
        LoopCallbacks with security, display, and tracing wired in.
    """
    def on_response(response: Response) -> None:
        show_response(response)
        tracer.record(
            "turn",
            stop_reason=response.stop_reason,
            response=response.message.content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def on_tool_call(tool_call: ToolCall) -> ToolResult:
        show_tool_call(tool_call)
        checked = hooks.run_before_tool(tool_call)
        if checked is None:
            tracer.record("tool_blocked", tool=tool_call.name, reason="safety_hook", args=tool_call.arguments)
            result = ToolResult(tool_call_id=tool_call.id, error="Blocked by safety hook")
            show_tool_result(result)
            return result
        if not permissions.check(checked):
            tracer.record("tool_denied", tool=tool_call.name, reason="user_denied", args=tool_call.arguments)
            result = ToolResult(tool_call_id=tool_call.id, error="Denied by user")
            show_tool_result(result)
            return result
        tracer.record("tool_call", tool=checked.name, args=checked.arguments)
        result = execute_tool(checked, max_output_chars=max_output_chars)
        result = hooks.run_after_tool(checked, result)
        tracer.record("tool_result", tool=checked.name, output=result.output, error=result.error)
        show_tool_result(result)
        return result

    def on_budget(usage: Usage) -> bool:
        exceeded = budget.record(usage)
        show_budget(budget.summary())
        tracer.record("budget", summary=budget.summary())
        return exceeded

    return LoopCallbacks(
        on_response=on_response,
        on_tool_call=on_tool_call,
        on_budget=on_budget,
    )


def _configure_tools(config: AgentConfig) -> None:
    """Set tool module globals from agent config.

    Args:
        config: Agent configuration.
    """
    from agent_harness import memory as memory_module
    from agent_harness import tools as tools_module
    tools_module.tool_timeout = config.tool_timeout
    tools_module.active_executor = config.executor
    memory_module.memory_dir = f"{config.agent_dir}/memory"
    tools_module.discover_tools("tools")


def _init_messages(config: AgentConfig, session_path: str | None) -> list[Message]:
    """Load session or create fresh message list.

    Args:
        config: Agent configuration.
        session_path: Path to session file, or None.

    Returns:
        Message list with system prompt.
    """
    messages = load_session(session_path) if session_path else []
    if not messages:
        messages = [Message(role="system", content=_build_system_prompt(config))]
    return messages


def _apply_overrides(config: AgentConfig, overrides: dict[str, object]) -> AgentConfig:
    """Apply CLI overrides to a loaded config.

    Args:
        config: Loaded agent configuration.
        overrides: Dict of field_name → value. None values are skipped.

    Returns:
        Config with overrides applied.
    """
    for key, value in overrides.items():
        if value is not None and hasattr(config, key):
            object.__setattr__(config, key, value)
    return config


def run_agent(
    agent_dir: str,
    prompt: str | None = None,
    session: str | None = None,
    verbose: bool = False,
    overrides: dict[str, object] | None = None,
) -> None:
    """Load config and run the agent loop.

    Args:
        agent_dir: Path to agent folder.
        prompt: Single prompt (None for REPL mode).
        session: Session name to save/resume.
        verbose: Enable verbose output.
        overrides: CLI config overrides (field_name → value).
    """
    try:
        config = config_loader.load(agent_dir)
        if overrides:
            _apply_overrides(config, overrides)
        validate_config(config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(agent_dir=config.agent_dir, verbose=verbose)
    _configure_tools(config)

    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    budget = Budget(config)
    hooks = Hooks(config.hooks, domain_prompt_fn=_domain_prompt, agent_dir=config.agent_dir)
    permissions = Permissions(config.permissions, prompt_fn=_permission_prompt)
    tracer = Tracer(f"{config.agent_dir}/logs")
    _trace_context(tracer, config)
    tool_schemas = [generate_schema(tool_registry[t]) for t in config.tools]
    callbacks = _make_callbacks(budget, hooks, permissions, tracer, config.max_output_chars)
    session_path = f"{config.agent_dir}/sessions/{session}.json" if session else None
    messages = _init_messages(config, session_path)

    if prompt:
        tracer.record("user_prompt", content=prompt)
        messages.append(Message(role="user", content=prompt))
        loop_fn(chat_fn, messages, tool_schemas, config, callbacks)
        if session_path:
            save_session(messages, session_path)
        return

    try:
        while True:
            user_input = prompt_user()
            if user_input.strip().lower() in ("exit", "quit"):
                break
            tracer.record("user_prompt", content=user_input)
            messages.append(Message(role="user", content=user_input))
            loop_fn(chat_fn, messages, tool_schemas, config, callbacks)
            if session_path:
                save_session(messages, session_path)
    except (KeyboardInterrupt, EOFError):
        print()
        if session_path:
            save_session(messages, session_path)


def main() -> None:
    """Entry point for CLI."""
    load_dotenv()
    args = parse_args()
    if args.command == "run":
        overrides = {
            "provider": args.provider,
            "model": args.model,
            "loop": args.loop,
            "max_turns": args.max_turns,
            "max_cost": args.max_cost,
            "executor": args.executor,
            "tool_timeout": args.tool_timeout,
            "max_output_chars": args.max_output_chars,
        }
        run_agent(args.agent_dir, prompt=args.prompt, session=args.session, verbose=args.verbose, overrides=overrides)
    elif args.command == "init":
        agent_dir = f"agents/{args.name}"
        create_agent(agent_dir)
        print(f"Created agent: {agent_dir}")
    else:
        parse_args(["--help"])
