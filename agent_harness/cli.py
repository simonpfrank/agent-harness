"""CLI entry point — wires terminal input to the shared runtime."""

from __future__ import annotations

import argparse
import json
import re
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.text import Text

from agent_harness import config as config_loader
from agent_harness.display import prompt_user
from agent_harness.log import setup_logging
from agent_harness.permissions import PermissionDecision
from agent_harness.runtime import (
    prepare_runtime,
)
from agent_harness.runtime import (
    validate_config as runtime_validate_config,
)
from agent_harness.scaffold import create_agent
from agent_harness.session import save_session
from agent_harness.types import AgentConfig, ToolCall

_console = Console()


def validate_config(config: AgentConfig) -> None:
    """Validate a loaded config.

    Args:
        config: Loaded agent config to validate.
    """
    runtime_validate_config(config)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list. Defaults to `sys.argv[1:]`.

    Returns:
        Parsed argument namespace.
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
    run_parser.add_argument("--temperature", type=float, default=None, help="Override sampling temperature")
    run_parser.add_argument(
        "--stream", action=argparse.BooleanOptionalAction, default=None, help="Override streaming (anthropic only)",
    )
    run_parser.add_argument(
        "--show-thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override whether extended thinking is displayed",
    )

    init_parser = sub.add_parser("init", help="Create a new agent")
    init_parser.add_argument("name", help="Agent name")

    return parser.parse_args(argv)


def _apply_overrides(config: AgentConfig, overrides: dict[str, object]) -> AgentConfig:
    """Apply CLI overrides to a loaded config.

    Args:
        config: Loaded agent configuration.
        overrides: Mapping of config field names to override values.

    Returns:
        Updated config object.
    """
    for key, value in overrides.items():
        if value is None:
            continue
        if key == "temperature":
            config.provider_kwargs["temperature"] = value
        elif hasattr(config, key):
            object.__setattr__(config, key, value)
    return config


_BRACKETED_CHOICE = re.compile(r"\[([^\[\]]+)\]")


def _highlight_choices(prompt: str) -> Text:
    """Style each `[x]`-bracketed choice so the keystroke it needs stands out.

    Args:
        prompt: Static prompt hint text containing `[x]`-style choice markers.

    Returns:
        A `Text` with the bracketed content styled `bold cyan`.
    """
    result = Text()
    pos = 0
    for match in _BRACKETED_CHOICE.finditer(prompt):
        result.append(prompt[pos : match.start()])
        result.append("[")
        result.append(match.group(1), style="bold cyan")
        result.append("]")
        pos = match.end()
    result.append(prompt[pos:])
    return result


def _permission_prompt(tool_call: ToolCall) -> PermissionDecision:
    """Ask the user whether to allow a tool call.

    Args:
        tool_call: Tool call requesting approval.

    Returns:
        Explicit permission decision selected by the user.
    """
    args_str = json.dumps(tool_call.arguments, indent=2)
    _console.print(Text("Tool: ", style="bold yellow") + Text(tool_call.name))
    _console.print(Text("Args: ", style="bold yellow") + Text(args_str))
    choice = _console.input(
        _highlight_choices("[o]nce / allow for [s]ession / allow [p]ersistently / [d]eny? "),
        markup=False,
    ).strip().lower()
    if choice == "o":
        return PermissionDecision.allow_once()
    if choice == "p":
        return PermissionDecision.allow_persistent()
    if choice == "s":
        return PermissionDecision.allow_session()
    return PermissionDecision.deny()


def _domain_prompt(domain: str) -> bool:
    """Ask the user whether to allow network access to a domain.

    Args:
        domain: Domain requesting access.

    Returns:
        `True` if the user approves the domain for this workspace.
    """
    _console.print(
        Text("Allow network access to ", style="bold yellow")
        + Text(domain, style="cyan")
        + Text("?", style="bold yellow"),
    )
    choice = _console.input(_highlight_choices("[y/n] "), markup=False).strip().lower()
    return choice in ("y", "yes")


def _plan_prompt(steps: list[str]) -> bool:
    """Ask the user whether to approve a generated plan before it executes.

    Args:
        steps: Numbered plan steps.

    Returns:
        `True` if the user approves executing the plan.
    """
    _console.print(Text("Proposed plan:", style="bold yellow"))
    for i, step in enumerate(steps, start=1):
        _console.print(Text(f"  {i}. {step}"))
    choice = _console.input(_highlight_choices("Approve this plan? [y/n] "), markup=False).strip().lower()
    return choice in ("y", "yes")


def run_agent(
    agent_dir: str,
    prompt: str | None = None,
    session: str | None = None,
    verbose: bool = False,
    overrides: dict[str, object] | None = None,
) -> None:
    """Load config and run the agent loop.

    Args:
        agent_dir: Agent directory path.
        prompt: Optional single-shot prompt. If omitted, enters REPL mode.
        session: Optional session name used for save/resume.
        verbose: Whether to enable verbose logging.
        overrides: Optional CLI config overrides.
    """
    try:
        config = config_loader.load(agent_dir)
        if overrides:
            _apply_overrides(config, overrides)
        runtime = prepare_runtime(
            config,
            permission_prompt_fn=_permission_prompt,
            domain_prompt_fn=_domain_prompt,
            plan_prompt_fn=_plan_prompt,
            show_output=True,
            trace_enabled=True,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(agent_dir=config.agent_dir, verbose=verbose)
    session_path = f"{config.agent_dir}/sessions/{session}.json" if session else None
    messages = runtime.init_messages(session_path=session_path)

    if prompt:
        runtime.run_messages(messages, prompt=prompt)
        if session_path:
            save_session(messages, session_path)
        runtime.finalize()
        return

    try:
        while True:
            user_input = prompt_user()
            if user_input.strip().lower() in ("exit", "quit"):
                break
            if not user_input.strip():
                continue
            runtime.run_messages(messages, prompt=user_input)
            if session_path:
                save_session(messages, session_path)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        if session_path:
            save_session(messages, session_path)
        runtime.finalize()


def main() -> None:
    """Entry point for the `agent_harness` CLI."""
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
            "temperature": args.temperature,
            "stream": args.stream,
            "show_thinking": args.show_thinking,
        }
        run_agent(args.agent_dir, prompt=args.prompt, session=args.session, verbose=args.verbose, overrides=overrides)
    elif args.command == "init":
        agent_dir = f"agents/{args.name}"
        create_agent(agent_dir)
        print(f"Created agent: {agent_dir}")
    else:
        parse_args(["--help"])
