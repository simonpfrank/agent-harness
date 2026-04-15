"""OpenAI provider for agent_harness."""

from __future__ import annotations

import json
from typing import Any

import openai

from agent_harness.providers.retry import with_retry
from agent_harness.types import Message, Response, ToolCall, Usage

_clients: dict[str, openai.OpenAI] = {}


def _get_client(base_url: str | None = None, api_key: str | None = None) -> openai.OpenAI:
    """Get or create an OpenAI client, keyed by base_url.

    Args:
        base_url: Custom API endpoint (e.g. LM Studio).
        api_key: Custom API key. Defaults to OPENAI_API_KEY env var.

    Returns:
        OpenAI client instance.
    """
    cache_key = base_url or "default"
    if cache_key not in _clients:
        kwargs: dict[str, Any] = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        elif base_url:
            kwargs["api_key"] = "not-needed"
        _clients[cache_key] = openai.OpenAI(**kwargs)
    return _clients[cache_key]


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal Messages to OpenAI API format.

    Args:
        messages: Internal message list.

    Returns:
        List of OpenAI-formatted message dicts.
    """
    result: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "tool" and msg.tool_result is not None:
            tr = msg.tool_result
            result.append({
                "role": "tool",
                "tool_call_id": tr.tool_call_id,
                "content": tr.output if tr.output else (tr.error or ""),
            })
            continue

        if msg.role == "assistant" and msg.tool_calls:
            api_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
            result.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": api_tool_calls,
            })
            continue

        result.append({"role": msg.role, "content": msg.content or ""})

    return result


def _to_openai_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tool schemas to OpenAI function-calling format.

    Args:
        schemas: Tool schemas in our internal format.

    Returns:
        Tool definitions in OpenAI API format.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


def _to_response(api_response: Any) -> Response:
    """Convert OpenAI API response to internal Response.

    Args:
        api_response: Raw response from OpenAI client.

    Returns:
        Internal Response object.
    """
    choice = api_response.choices[0]
    content = choice.message.content
    tool_calls: list[ToolCall] | None = None

    if choice.message.tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments),
            )
            for tc in choice.message.tool_calls
        ]

    # OpenAI sometimes returns finish_reason="stop" even with tool_calls present.
    # Check tool_calls directly rather than trusting finish_reason alone.
    stop_reason = "tool_use" if tool_calls else "end_turn"

    message = Message(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
    )
    usage = Usage(
        input_tokens=api_response.usage.prompt_tokens,
        output_tokens=api_response.usage.completion_tokens,
    )
    return Response(message=message, usage=usage, stop_reason=stop_reason)


def chat(
    messages: list[Message],
    tools: list[dict[str, Any]],
    model: str = "gpt-4o-mini",
    **kwargs: Any,
) -> Response:
    """Send messages to OpenAI and return a Response.

    Args:
        messages: Conversation history.
        tools: Tool schemas for function calling.
        model: Model identifier.
        **kwargs: Additional API parameters.

    Returns:
        Parsed Response with message, usage, and stop_reason.
    """
    api_messages = _to_openai_messages(messages)
    api_tools = _to_openai_tools(tools)

    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": api_messages,
    }
    is_reasoning = model.startswith(("o1", "o3", "o4"))
    if is_reasoning:
        if "max_tokens" in kwargs:
            create_kwargs["max_completion_tokens"] = kwargs["max_tokens"]
    else:
        for key in ("temperature", "max_tokens", "top_p"):
            if key in kwargs:
                create_kwargs[key] = kwargs[key]
    if api_tools:
        create_kwargs["tools"] = api_tools

    client = _get_client(
        base_url=kwargs.get("base_url"),
        api_key=kwargs.get("api_key"),
    )
    def _call() -> Response:
        return _to_response(client.chat.completions.create(**create_kwargs))

    result: Response = with_retry(
        _call,
        auth_error=openai.AuthenticationError,
        bad_request_error=openai.BadRequestError,
        api_error=openai.APIError,
        provider_name="OpenAI",
        env_var="OPENAI_API_KEY",
    )
    return result
