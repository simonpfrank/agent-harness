"""CLI composition root — wires everything together."""

from __future__ import annotations

import argparse
import json
import sys

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
from agent_harness.tools import execute_tool, generate_schema
from agent_harness.tools import registry as tool_registry
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


def _build_system_prompt(config: AgentConfig) -> str:
    """Combine instructions and tools guidance into a system prompt.

    Args:
        config: Agent configuration.

    Returns:
        System prompt string.
    """
    prompt = config.instructions
    if config.tools_guidance:
        prompt += "\n\n" + config.tools_guidance
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
    budget: Budget, hooks: Hooks, permissions: Permissions, max_output_chars: int = 10_000,
) -> LoopCallbacks:
    """Create display callbacks with hooks and permissions.

    Args:
        budget: Budget tracker.
        hooks: Safety hooks.
        permissions: Tool permissions.

    Returns:
        LoopCallbacks with security and display wired in.
    """
    def on_response(response: Response) -> None:
        show_response(response)

    def on_tool_call(tool_call: ToolCall) -> ToolResult:
        show_tool_call(tool_call)
        checked = hooks.run_before_tool(tool_call)
        if checked is None:
            result = ToolResult(tool_call_id=tool_call.id, error="Blocked by safety hook")
            show_tool_result(result)
            return result
        if not permissions.check(checked):
            result = ToolResult(tool_call_id=tool_call.id, error="Denied by user")
            show_tool_result(result)
            return result
        result = execute_tool(checked, max_output_chars=max_output_chars)
        result = hooks.run_after_tool(checked, result)
        show_tool_result(result)
        return result

    def on_budget(usage: Usage) -> bool:
        exceeded = budget.record(usage)
        show_budget(budget.summary())
        return exceeded

    return LoopCallbacks(
        on_response=on_response,
        on_tool_call=on_tool_call,
        on_budget=on_budget,
    )


def run_agent(
    agent_dir: str,
    prompt: str | None = None,
    session: str | None = None,
    verbose: bool = False,
) -> None:
    """Load config and run the agent loop.

    Args:
        agent_dir: Path to agent folder.
        prompt: Single prompt (None for REPL mode).
        session: Session name to save/resume.
        verbose: Enable verbose output.
    """
    try:
        config = config_loader.load(agent_dir)
        validate_config(config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(agent_dir=config.agent_dir, verbose=verbose)

    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    budget = Budget(config)
    hooks = Hooks(config.hooks, domain_prompt_fn=_domain_prompt, agent_dir=config.agent_dir)
    permissions = Permissions(config.permissions, prompt_fn=_permission_prompt)
    from agent_harness import tools as tools_module
    tools_module.tool_timeout = config.tool_timeout
    tools_module.active_executor = config.executor
    tools_module.memory_dir = f"{config.agent_dir}/memory"
    tool_schemas = [generate_schema(tool_registry[t]) for t in config.tools]
    callbacks = _make_callbacks(budget, hooks, permissions, config.max_output_chars)
    system_prompt = _build_system_prompt(config)
    session_path = f"{config.agent_dir}/sessions/{session}.json" if session else None
    messages = load_session(session_path) if session_path else []
    if not messages:
        messages = [Message(role="system", content=system_prompt)]

    if prompt:
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
        run_agent(args.agent_dir, prompt=args.prompt, session=args.session, verbose=args.verbose)
    elif args.command == "init":
        agent_dir = f"agents/{args.name}"
        create_agent(agent_dir)
        print(f"Created agent: {agent_dir}")
    else:
        parse_args(["--help"])
