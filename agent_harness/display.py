"""Rich console output for agent_harness."""

from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from agent_harness.types import Response, ToolCall, ToolResult

console = Console()


def show_response(response: Response) -> None:
    """Render assistant text as markdown.

    Args:
        response: The LLM response to display.
    """
    content = response.message.content
    if content:
        console.print(Markdown(content))


def show_tool_call(tool_call: ToolCall) -> None:
    """Display a tool invocation in a panel.

    Args:
        tool_call: The tool call to display.
    """
    args_str = json.dumps(tool_call.arguments, indent=2)
    console.print(Panel(args_str, title=f"Tool: {tool_call.name}", border_style="blue"))


def show_tool_result(result: ToolResult) -> None:
    """Display a tool result in a panel.

    Args:
        result: The tool result to display.
    """
    if result.error:
        console.print(Panel(result.error, title="Error", border_style="red"))
    else:
        output = result.output or ""
        truncated = output[:2000] + "..." if len(output) > 2000 else output
        console.print(Panel(truncated, title="Result", border_style="green"))


def show_budget(summary: str) -> None:
    """Display budget status as a dim line.

    Args:
        summary: Human-readable budget summary string.
    """
    console.print(f"[dim]{summary}[/dim]")


def prompt_user() -> str:
    """Styled input prompt.

    Returns:
        The user's input string.
    """
    return console.input("[bold cyan]> [/bold cyan]")
