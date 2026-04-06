"""Anthropic (Claude) provider for agent_harness."""

from __future__ import annotations

from typing import Any

import anthropic

from agent_harness.types import Message, Response, ToolCall, Usage

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy client creation — avoids import-time API key errors."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _tool_result_to_api(msg: Message) -> dict[str, Any]:
    """Convert a tool result message to Anthropic API format.

    Args:
        msg: Message with role="tool" and tool_result set.

    Returns:
        API-formatted message dict.
    """
    tr = msg.tool_result
    assert tr is not None
    return {
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tr.tool_call_id,
            "content": tr.output if tr.output else (tr.error or ""),
            "is_error": tr.error is not None,
        }],
    }


def _assistant_with_tools_to_api(msg: Message) -> dict[str, Any]:
    """Convert an assistant message with tool calls to Anthropic API format.

    Args:
        msg: Message with role="assistant" and tool_calls set.

    Returns:
        API-formatted message dict.
    """
    content: list[dict[str, Any]] = []
    if msg.content:
        content.append({"type": "text", "text": msg.content})
    for tc in msg.tool_calls or []:
        content.append({
            "type": "tool_use",
            "id": tc.id,
            "name": tc.name,
            "input": tc.arguments,
        })
    return {"role": "assistant", "content": content}


def _to_anthropic_messages(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert internal Messages to Anthropic API format.

    Args:
        messages: Internal message list.

    Returns:
        Tuple of (system_prompt, api_messages).
    """
    system: str | None = None
    result: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            system = msg.content
        elif msg.role == "tool" and msg.tool_result is not None:
            result.append(_tool_result_to_api(msg))
        elif msg.role == "assistant" and msg.tool_calls:
            result.append(_assistant_with_tools_to_api(msg))
        else:
            result.append({"role": msg.role, "content": msg.content or ""})

    return system, result


def _to_anthropic_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tool schemas to Anthropic format.

    Args:
        schemas: Tool schemas in our internal format.

    Returns:
        Tool definitions in Anthropic API format.
    """
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "input_schema": s["input_schema"],
        }
        for s in schemas
    ]


def _to_response(api_response: Any) -> Response:
    """Convert Anthropic API response to internal Response.

    Args:
        api_response: Raw response from Anthropic client.

    Returns:
        Internal Response object.
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in api_response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input,
            ))

    content = "\n".join(text_parts) if text_parts else None
    message = Message(
        role="assistant",
        content=content,
        tool_calls=tool_calls if tool_calls else None,
    )
    usage = Usage(
        input_tokens=api_response.usage.input_tokens,
        output_tokens=api_response.usage.output_tokens,
    )
    return Response(message=message, usage=usage, stop_reason=api_response.stop_reason)


def chat(
    messages: list[Message],
    tools: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    **kwargs: Any,
) -> Response:
    """Send messages to Anthropic and return a Response.

    Args:
        messages: Conversation history.
        tools: Tool schemas for function calling.
        model: Model identifier.
        **kwargs: Additional API parameters.

    Returns:
        Parsed Response with message, usage, and stop_reason.
    """
    system, api_messages = _to_anthropic_messages(messages)
    api_tools = _to_anthropic_tools(tools)

    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": api_messages,
        "max_tokens": kwargs.get("max_tokens", 4096),
    }
    if system:
        create_kwargs["system"] = system
    if api_tools:
        create_kwargs["tools"] = api_tools

    api_response = _get_client().messages.create(**create_kwargs)
    return _to_response(api_response)
