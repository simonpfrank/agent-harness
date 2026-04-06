"""CLI composition root — wires everything together."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from agent_harness import config as config_loader
from agent_harness.budget import Budget
from agent_harness.display import (
    prompt_user,
    show_budget,
    show_response,
    show_tool_call,
    show_tool_result,
)
from agent_harness.loops import registry as loop_registry
from agent_harness.providers import registry as provider_registry
from agent_harness.tools import execute_tool, generate_schema
from agent_harness.tools import registry as tool_registry
from agent_harness.types import Message, Response, ToolCall, ToolResult, Usage


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
    run_parser.add_argument("--verbose", action="store_true", help="Verbose output")

    return parser.parse_args(argv)


def run_agent(agent_dir: str, prompt: str | None = None, verbose: bool = False) -> None:
    """Load config and run the agent loop.

    Args:
        agent_dir: Path to agent folder.
        prompt: Single prompt (None for REPL mode).
        verbose: Enable verbose output.
    """
    try:
        config = config_loader.load(agent_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    chat_fn = provider_registry[config.provider]
    loop_fn = loop_registry[config.loop]
    budget = Budget(config)

    tool_schemas = [generate_schema(tool_registry[t]) for t in config.tools]

    def on_response(response: Response) -> None:
        show_response(response)

    def on_tool_call(tool_call: ToolCall) -> ToolResult:
        show_tool_call(tool_call)
        result = execute_tool(tool_call)
        show_tool_result(result)
        return result

    def on_budget(usage: Usage) -> bool:
        exceeded = budget.record(usage)
        show_budget(budget.summary())
        return exceeded

    system_prompt = config.instructions
    if config.tools_guidance:
        system_prompt += "\n\n" + config.tools_guidance

    def run_once(user_prompt: str, messages: list[Message]) -> list[Message]:
        messages.append(Message(role="user", content=user_prompt))
        loop_fn(
            chat_fn, messages, tool_schemas, config,
            on_response=on_response,
            on_tool_call=on_tool_call,
            on_budget=on_budget,
        )
        return messages

    messages: list[Message] = [Message(role="system", content=system_prompt)]

    if prompt:
        run_once(prompt, messages)
        return

    # REPL mode
    try:
        while True:
            user_input = prompt_user()
            if user_input.strip().lower() in ("exit", "quit"):
                break
            run_once(user_input, messages)
    except (KeyboardInterrupt, EOFError):
        print()


def main() -> None:
    """Entry point for CLI."""
    load_dotenv()
    args = parse_args()
    if args.command == "run":
        run_agent(args.agent_dir, prompt=args.prompt, verbose=args.verbose)
    else:
        parse_args(["--help"])
