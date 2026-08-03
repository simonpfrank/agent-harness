"""Anthropic (Claude) provider for agent_harness."""

from __future__ import annotations

from typing import Any

import anthropic

from agent_harness.providers.retry import with_retry
from agent_harness.types import Message, Response, ToolCall, Usage

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy client creation — avoids import-time API key errors."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


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
            continue

        if msg.role == "tool" and msg.tool_result is not None:
            tr = msg.tool_result
            tool_result_block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tr.tool_call_id,
                "content": tr.output if tr.output else (tr.error or ""),
                "is_error": tr.error is not None,
            }
            # Merge consecutive tool results into one user message
            if result and result[-1].get("role") == "user":
                prev_content = result[-1].get("content", [])
                if isinstance(prev_content, list) and prev_content and prev_content[0].get("type") == "tool_result":
                    prev_content.append(tool_result_block)
                    continue
            result.append({"role": "user", "content": [tool_result_block]})
            continue

        if msg.role == "assistant" and (msg.tool_calls or msg.thinking_blocks):
            content: list[dict[str, Any]] = []
            if msg.thinking_blocks:
                content.extend(msg.thinking_blocks)
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls or []:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            result.append({"role": "assistant", "content": content})
            continue

        # Merge consecutive same-role messages (Anthropic requires alternation)
        if result and result[-1].get("role") == msg.role:
            prev = result[-1]
            prev_content = prev.get("content", "")
            if isinstance(prev_content, str):
                prev["content"] = prev_content + "\n" + (msg.content or "")
            elif isinstance(prev_content, list):
                prev_content.append({"type": "text", "text": msg.content or ""})
            continue
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
    thinking_parts: list[str] = []
    thinking_blocks: list[dict[str, Any]] = []

    for block in api_response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input,
            ))
        elif block.type == "thinking":
            thinking_parts.append(block.thinking)
            thinking_blocks.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature})
        elif block.type == "redacted_thinking":
            thinking_blocks.append({"type": "redacted_thinking", "data": block.data})

    content = "\n".join(text_parts) if text_parts else None
    message = Message(
        role="assistant",
        content=content,
        tool_calls=tool_calls if tool_calls else None,
        thinking="\n".join(thinking_parts) if thinking_parts else None,
        thinking_blocks=thinking_blocks if thinking_blocks else None,
    )
    usage = Usage(
        input_tokens=api_response.usage.input_tokens,
        output_tokens=api_response.usage.output_tokens,
    )
    return Response(message=message, usage=usage, stop_reason=api_response.stop_reason)


def _apply_thinking(create_kwargs: dict[str, Any], thinking: dict[str, Any], kwargs: dict[str, Any]) -> None:
    """Validate and apply extended-thinking config to request kwargs.

    Args:
        create_kwargs: Request kwargs being built, mutated in place.
        thinking: Thinking config, e.g. `{"budget_tokens": 2000}`.
        kwargs: Original caller kwargs, checked for incompatible overrides.

    Raises:
        ValueError: If budget_tokens is invalid, or temperature/top_p is also set.
    """
    budget_tokens = thinking["budget_tokens"]
    if budget_tokens < 1024:
        raise ValueError(f"thinking.budget_tokens must be >= 1024, got {budget_tokens}")
    if budget_tokens >= create_kwargs["max_tokens"]:
        raise ValueError(
            f"thinking.budget_tokens ({budget_tokens}) must be less than max_tokens ({create_kwargs['max_tokens']})",
        )
    if "temperature" in kwargs or "top_p" in kwargs:
        raise ValueError("extended thinking is incompatible with temperature/top_p overrides")
    create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}


def _stream_deltas(stream: Any, on_delta: Any, on_thinking_delta: Any) -> Response:
    """Consume a MessageStream, dispatching deltas, and return the final Response.

    Args:
        stream: Open `MessageStream` context manager value.
        on_delta: Optional callback for text deltas, `(agent_id, chunk)`.
        on_thinking_delta: Optional callback for thinking deltas, `(agent_id, chunk)`.

    Returns:
        Parsed Response built from the stream's final accumulated message.
    """
    for event in stream:
        if event.type != "content_block_delta":
            continue
        if event.delta.type == "text_delta" and on_delta is not None:
            on_delta("default", event.delta.text)
        elif event.delta.type == "thinking_delta" and on_thinking_delta is not None:
            on_thinking_delta("default", event.delta.thinking)
    return _to_response(stream.get_final_message())


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
        **kwargs: Additional API parameters — `temperature`, `top_p`,
            `max_tokens`, `thinking` (`{"budget_tokens": int}`), `stream`
            (bool), `on_delta`/`on_thinking_delta` (`(agent_id, chunk) ->
            None`, only used when `stream=True`).

    Returns:
        Parsed Response with message, usage, and stop_reason.

    Raises:
        ValueError: If `thinking` is set with an invalid budget or alongside
            `temperature`/`top_p`.
    """
    system, api_messages = _to_anthropic_messages(messages)
    api_tools = _to_anthropic_tools(tools)

    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": api_messages,
        "max_tokens": kwargs.get("max_tokens", 4096),
    }
    thinking = kwargs.get("thinking")
    if thinking is not None:
        _apply_thinking(create_kwargs, thinking, kwargs)
    for key in ("temperature", "top_p"):
        if key in kwargs:
            create_kwargs[key] = kwargs[key]
    if system:
        create_kwargs["system"] = system
    if api_tools:
        create_kwargs["tools"] = api_tools

    stream = kwargs.get("stream", False)
    on_delta = kwargs.get("on_delta")
    on_thinking_delta = kwargs.get("on_thinking_delta")

    def _call() -> Response:
        if stream:
            with _get_client().messages.stream(**create_kwargs) as message_stream:
                return _stream_deltas(message_stream, on_delta, on_thinking_delta)
        return _to_response(_get_client().messages.create(**create_kwargs))

    result: Response = with_retry(
        _call,
        auth_error=anthropic.AuthenticationError,
        bad_request_error=anthropic.BadRequestError,
        api_error=anthropic.APIError,
        provider_name="Anthropic",
        env_var="ANTHROPIC_API_KEY",
    )
    return result
