"""OpenAI provider for agent_harness.

This module exposes one harness-facing provider while hiding OpenAI endpoint
differences internally. Hosted OpenAI text models use the Responses API by
default; OpenAI-compatible backends reached via `base_url` continue to use
Chat Completions for compatibility.
"""

from __future__ import annotations

import json
from typing import Any, cast

import openai

from agent_harness.models import MODEL_REGISTRY
from agent_harness.providers.retry import with_retry
from agent_harness.types import Attachment, Message, Response, ToolCall, ToolResult, Usage

_clients: dict[str, openai.OpenAI] = {}
_EXCLUDED_MODEL_PREFIXES = ("o1", "o3", "o4")


def _coerce_usage_int(value: Any, fallback: int = 0) -> int:
    """Convert a usage field to an integer token count."""
    if isinstance(value, int):
        return value
    return fallback


def _get_client(
    base_url: str | None = None, api_key: str | None = None
) -> openai.OpenAI:
    """Get or create an OpenAI client, keyed by base URL.

    Args:
        base_url: Custom API endpoint for OpenAI-compatible backends.
        api_key: Custom API key. Defaults to `OPENAI_API_KEY`.

    Returns:
        Cached OpenAI client instance.
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


def _response_endpoint_for_model(model: str, base_url: str | None = None) -> str:
    """Choose the internal OpenAI endpoint for a model.

    Args:
        model: Model identifier.
        base_url: Optional custom backend URL. When set, compatibility is
            preferred over hosted-model routing and Chat Completions is used.

    Returns:
        Either `"responses"` or `"chat_completions"`.

    Raises:
        ValueError: If the model is an o-series reasoning model, which this
            provider deliberately excludes.
    """
    if base_url:
        return "chat_completions"
    if model.startswith(_EXCLUDED_MODEL_PREFIXES):
        raise ValueError(
            f"Unsupported OpenAI model '{model}': o-series reasoning models are not supported.",
        )
    return "responses"


def _chat_completions_attachment_message(attachment: Attachment) -> dict[str, Any]:
    """Build the follow-up message for a viewed image/document over Chat Completions.

    Chat Completions has no document/file content type at all — a PDF
    attachment becomes a short in-band text note instead of a raw
    BadRequestError, since that incompatibility is known ahead of time,
    not genuine model-capability variance.

    Args:
        attachment: The attachment to render.

    Returns:
        A synthetic user message to append after the tool result.
    """
    if attachment.kind == "document":
        name = attachment.filename or "the document"
        note = f"[Note: {name} is a PDF; this backend does not support document viewing over Chat Completions.]"
        return {"role": "user", "content": note}
    url = f"data:{attachment.media_type};base64,{attachment.data}"
    return {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}


def _append_chat_completions_tool_result(result: list[dict[str, Any]], tr: ToolResult) -> None:
    result.append(
        {
            "role": "tool",
            "tool_call_id": tr.tool_call_id,
            "content": tr.output if tr.output else (tr.error or ""),
        },
    )
    if tr.attachment is not None:
        result.append(_chat_completions_attachment_message(tr.attachment))


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal messages to Chat Completions format.

    Args:
        messages: Internal message list.

    Returns:
        List of Chat Completions message objects.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "tool" and msg.tool_result is not None:
            _append_chat_completions_tool_result(result, msg.tool_result)
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
            result.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": api_tool_calls,
                },
            )
            continue

        result.append({"role": msg.role, "content": msg.content or ""})
    return result


def _responses_attachment_item(attachment: Attachment) -> dict[str, Any]:
    """Build the follow-up input item for a viewed image/document over the Responses API.

    Args:
        attachment: The attachment to render.

    Returns:
        A synthetic user input item to append after the function_call_output.
    """
    url = f"data:{attachment.media_type};base64,{attachment.data}"
    if attachment.kind == "document":
        content: dict[str, Any] = {
            "type": "input_file",
            "file_data": url,
            "filename": attachment.filename or "document.pdf",
        }
    else:
        content = {"type": "input_image", "image_url": url}
    return {"role": "user", "content": [content]}


def _append_responses_tool_result(input_items: list[dict[str, Any]], tr: ToolResult) -> None:
    input_items.append(
        {
            "type": "function_call_output",
            "call_id": tr.tool_call_id,
            "output": tr.output if tr.output else (tr.error or ""),
        },
    )
    if tr.attachment is not None:
        input_items.append(_responses_attachment_item(tr.attachment))


def _to_openai_input(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert internal messages to Responses API instructions and input items.

    Args:
        messages: Internal conversation history.

    Returns:
        Tuple of merged system instructions and Responses input items.
    """
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            if msg.content:
                instructions.append(msg.content)
            continue

        if msg.role == "tool" and msg.tool_result is not None:
            _append_responses_tool_result(input_items, msg.tool_result)
            continue

        if msg.role == "assistant" and msg.tool_calls:
            for tool_call in msg.tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments),
                    },
                )
            continue

        input_items.append({"role": msg.role, "content": msg.content or ""})

    merged_instructions = "\n\n".join(instructions) if instructions else None
    return merged_instructions, input_items


def _to_openai_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tool schemas to Chat Completions tool format.

    Args:
        schemas: Internal tool schemas.

    Returns:
        Chat Completions tool definitions.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            },
        }
        for schema in schemas
    ]


def _to_responses_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tool schemas to Responses API tool format.

    Args:
        schemas: Internal tool schemas.

    Returns:
        Responses API tool definitions.
    """
    return [
        {
            "type": "function",
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["input_schema"],
            # Keep schema handling permissive to match the harness' existing
            # best-effort function-calling behavior.
            "strict": False,
        }
        for schema in schemas
    ]


def _usage_to_internal(api_response: Any) -> Usage:
    """Map OpenAI usage objects to the harness usage type.

    Args:
        api_response: Raw API response from either OpenAI endpoint.

    Returns:
        Internal Usage object.
    """
    usage = getattr(api_response, "usage", None)
    if usage is None:
        return Usage(input_tokens=0, output_tokens=0)
    input_tokens = getattr(usage, "input_tokens", None)
    if not isinstance(input_tokens, int):
        input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(output_tokens, int):
        output_tokens = getattr(usage, "completion_tokens", 0)
    return Usage(
        input_tokens=_coerce_usage_int(input_tokens),
        output_tokens=_coerce_usage_int(output_tokens),
    )


def _responses_to_response(api_response: Any) -> Response:
    """Convert a Responses API object to the harness response type.

    Args:
        api_response: Responses API object.

    Returns:
        Parsed internal response.
    """
    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for item in getattr(api_response, "output", []):
        item_type = getattr(item, "type", "")
        if item_type == "function_call":
            tool_calls.append(
                ToolCall(
                    id=item.call_id,
                    name=item.name,
                    arguments=json.loads(item.arguments),
                ),
            )
            continue
        if item_type != "message":
            continue
        for part in getattr(item, "content", []):
            if getattr(part, "type", "") == "output_text":
                content_parts.append(part.text)

    message = Message(
        role="assistant",
        content="".join(content_parts) or None,
        tool_calls=tool_calls or None,
    )
    stop_reason = "tool_use" if tool_calls else "end_turn"
    return Response(
        message=message, usage=_usage_to_internal(api_response), stop_reason=stop_reason
    )


def _chat_completions_to_response(api_response: Any) -> Response:
    """Convert a Chat Completions response to the harness response type.

    Args:
        api_response: Chat Completions API response.

    Returns:
        Parsed internal response.
    """
    choice = api_response.choices[0]
    tool_calls: list[ToolCall] = []

    for tool_call in choice.message.tool_calls or []:
        tool_calls.append(
            ToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=json.loads(tool_call.function.arguments),
            ),
        )

    # LM Studio/vLLM-style backends return reasoning-model thinking on this
    # non-standard field — real hosted OpenAI responses simply don't have
    # it, so getattr(..., None) is the safe way to read it either way.
    reasoning = getattr(choice.message, "reasoning_content", None)
    message = Message(
        role="assistant",
        content=choice.message.content or None,
        tool_calls=tool_calls or None,
        thinking=reasoning or None,
    )
    stop_reason = "tool_use" if tool_calls else "end_turn"
    return Response(
        message=message, usage=_usage_to_internal(api_response), stop_reason=stop_reason
    )


def _to_response(api_response: Any) -> Response:
    """Convert either OpenAI response shape to the harness response type.

    Args:
        api_response: Raw API response from OpenAI.

    Returns:
        Internal Response object.
    """
    if getattr(api_response, "choices", None):
        return _chat_completions_to_response(api_response)
    return _responses_to_response(api_response)


def _build_create_kwargs(
    model: str,
    instructions: str | None,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float | None,
    max_tokens: int | None,
    top_p: float | None,
    base_url: str | None = None,
    messages: list[Message] | None = None,
    reasoning_effort: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Build OpenAI request kwargs from the compatibility matrix.

    Args:
        model: Model identifier.
        instructions: Optional merged system prompt for Responses.
        input_items: Responses-formatted input items.
        tools: Internal tool schemas.
        temperature: Optional temperature override.
        max_tokens: Optional token limit.
        top_p: Optional nucleus sampling override.
        base_url: Optional custom backend URL.
        stream: Whether to request streaming. Only affects the Chat
            Completions branch — Responses-API streaming goes through
            `client.responses.stream()` directly, not this dict.

    Returns:
        Request kwargs for either `responses.create` or
        `chat.completions.create`.
    """
    endpoint = _response_endpoint_for_model(model, base_url=base_url)
    if endpoint == "chat_completions":
        if messages is None:
            raise ValueError(
                "Chat Completions fallback requires the original message list."
            )
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if max_tokens is not None:
            create_kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            create_kwargs["top_p"] = top_p
        api_tools = _to_openai_tools(tools)
        if api_tools:
            create_kwargs["tools"] = api_tools
        if stream:
            create_kwargs["stream"] = True
            create_kwargs["stream_options"] = {"include_usage": True}
        return create_kwargs

    create_kwargs = {"model": model, "input": input_items}
    if instructions:
        create_kwargs["instructions"] = instructions
    if temperature is not None:
        create_kwargs["temperature"] = temperature
    if top_p is not None:
        create_kwargs["top_p"] = top_p
    if max_tokens is not None:
        create_kwargs["max_output_tokens"] = max_tokens
    spec = MODEL_REGISTRY.get(("openai", model))
    if reasoning_effort is not None:
        create_kwargs["reasoning"] = {"effort": reasoning_effort}
    elif spec is not None and spec.minimal_reasoning_default:
        create_kwargs["reasoning"] = {"effort": "minimal"}
    api_tools = _to_responses_tools(tools)
    if api_tools:
        create_kwargs["tools"] = api_tools
    return create_kwargs


def _stream_responses_deltas(stream: Any, on_delta: Any) -> Response:
    """Consume a ResponseStream, dispatching text deltas, and return the final Response.

    Args:
        stream: Open `ResponseStream` context manager value.
        on_delta: Optional callback for text deltas, `(agent_id, chunk)`.

    Returns:
        Parsed Response built from the stream's final accumulated response.
    """
    for event in stream:
        if event.type == "response.output_text.delta" and on_delta is not None:
            on_delta("default", event.delta)
    return _to_response(stream.get_final_response())


def _merge_tool_call_delta(fragments: dict[int, dict[str, Any]], tc_delta: Any) -> None:
    """Merge one streamed tool-call delta fragment into its per-index accumulator.

    Chat Completions tool-call deltas are keyed by `index` (stable across
    chunks for a given call), not by `id` — `id` and `function.name` only
    appear on the first fragment for that index; `function.arguments`
    arrives as a JSON-string fragment to be concatenated across chunks.

    Args:
        fragments: Accumulator keyed by `tc_delta.index`, mutated in place.
        tc_delta: A single tool-call delta fragment from one chunk.
    """
    fragment = fragments.setdefault(tc_delta.index, {"id": None, "name": None, "arguments": ""})
    if tc_delta.id is not None:
        fragment["id"] = tc_delta.id
    if tc_delta.function is not None:
        if tc_delta.function.name is not None:
            fragment["name"] = tc_delta.function.name
        if tc_delta.function.arguments is not None:
            fragment["arguments"] += tc_delta.function.arguments


def _stream_chat_completions_deltas(
    stream: Any, on_delta: Any, on_thinking_delta: Any = None, is_cancelled: Any = None,
) -> Response:
    """Consume a Chat Completions chunk stream, dispatching text deltas.

    Unlike `client.responses.stream()`, `client.chat.completions.create(
    stream=True)` returns a plain iterable, not a context manager — callers
    must not wrap this in a `with` block.

    Args:
        stream: Iterable of Chat Completions chunks.
        on_delta: Optional callback for text deltas, `(agent_id, chunk)`.
        on_thinking_delta: Optional callback for thinking deltas,
            `(agent_id, chunk)` — LM Studio/vLLM-style reasoning-model
            backends stream thinking as `delta.reasoning_content`, a
            separate field from `delta.content` (confirmed directly
            against a real LM Studio response, not assumed). Real hosted
            OpenAI Chat Completions responses simply never set this field.
        is_cancelled: Optional `() -> bool`, checked once per chunk. On
            `True`, stops consuming immediately and returns whatever was
            accumulated so far with `stop_reason="cancelled"` — this
            function already builds its `Response` entirely from local
            accumulation (not an SDK "final message"), so an early stop
            costs nothing extra to support.

    Returns:
        Parsed Response accumulated from the stream's chunks.
    """
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_call_fragments: dict[int, dict[str, Any]] = {}
    final_chunk: Any = None
    cancelled = False

    for chunk in stream:
        if is_cancelled is not None and is_cancelled():
            cancelled = True
            break
        if chunk.usage is not None:
            final_chunk = chunk
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            reasoning_parts.append(reasoning)
            if on_thinking_delta is not None:
                on_thinking_delta("default", reasoning)
        if delta.content:
            content_parts.append(delta.content)
            if on_delta is not None:
                on_delta("default", delta.content)
        for tc_delta in delta.tool_calls or []:
            _merge_tool_call_delta(tool_call_fragments, tc_delta)

    tool_calls = [
        ToolCall(
            id=fragment["id"],
            name=fragment["name"],
            arguments=json.loads(fragment["arguments"]) if fragment["arguments"] else {},
        )
        for _, fragment in sorted(tool_call_fragments.items())
    ]
    message = Message(
        role="assistant",
        content="".join(content_parts) or None,
        tool_calls=tool_calls or None,
        thinking="".join(reasoning_parts) or None,
    )
    stop_reason = "cancelled" if cancelled else ("tool_use" if tool_calls else "end_turn")
    return Response(message=message, usage=_usage_to_internal(final_chunk), stop_reason=stop_reason)


def chat(
    messages: list[Message],
    tools: list[dict[str, Any]],
    model: str = "gpt-4o-mini",
    **kwargs: Any,
) -> Response:
    """Send messages to OpenAI and return a harness response.

    Args:
        messages: Conversation history.
        tools: Tool schemas for function calling.
        model: Model identifier.
        **kwargs: Provider overrides such as `temperature`, `top_p`,
            `max_tokens`, `base_url`, `api_key`, `stream` (bool), or
            `on_delta`/`on_thinking_delta` (`(agent_id, chunk) -> None`,
            only used when `stream=True`). `on_thinking_delta` only fires
            for the Chat Completions path against a reasoning-model backend
            that streams `reasoning_content` (e.g. LM Studio) — the hosted
            Responses API path doesn't surface reasoning deltas yet.

    Returns:
        Parsed Response with message, usage, and stop reason.

    Raises:
        ValueError: If the hosted OpenAI model is intentionally unsupported.
    """
    base_url = kwargs.get("base_url")
    stream = kwargs.get("stream", False)
    instructions, input_items = _to_openai_input(messages)
    create_kwargs = _build_create_kwargs(
        model=model,
        instructions=instructions,
        input_items=input_items,
        tools=tools,
        temperature=kwargs.get("temperature"),
        max_tokens=kwargs.get("max_tokens"),
        top_p=kwargs.get("top_p"),
        base_url=base_url,
        messages=messages,
        reasoning_effort=kwargs.get("reasoning_effort"),
        stream=stream,
    )
    endpoint = _response_endpoint_for_model(model, base_url=base_url)
    client = _get_client(base_url=base_url, api_key=kwargs.get("api_key"))
    on_delta = kwargs.get("on_delta")
    on_thinking_delta = kwargs.get("on_thinking_delta")
    is_cancelled = kwargs.get("is_cancelled")

    def _call() -> Response:
        if endpoint == "chat_completions":
            if stream:
                return _stream_chat_completions_deltas(
                    client.chat.completions.create(**create_kwargs), on_delta, on_thinking_delta, is_cancelled,
                )
            return _to_response(client.chat.completions.create(**create_kwargs))
        if stream:
            with client.responses.stream(**create_kwargs) as response_stream:
                return _stream_responses_deltas(response_stream, on_delta)
        return _to_response(client.responses.create(**create_kwargs))

    return cast(
        Response,
        with_retry(
            _call,
            auth_error=openai.AuthenticationError,
            bad_request_error=openai.BadRequestError,
            api_error=openai.APIError,
            provider_name="OpenAI",
            env_var="OPENAI_API_KEY",
        ),
    )
