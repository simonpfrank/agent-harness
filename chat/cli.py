#!/usr/bin/env python3
"""Temporary plain-terminal diagnostic client for the agent-harness API.

No web layer, no rendering choices, no display state to get out of sync —
just the raw event stream, printed live with a timestamp on the left, so
timing and event ordering are directly visible. For working on the API
itself; the Streamlit app in chat/app.py can come back to this once the
API side is solid.

Note: Ctrl-C stops *this script's* view of the stream — the server has no
cancellation support yet, so a run already in progress keeps running
server-side regardless (see docs/api-plan.md's "deferred" list).

Usage:
    python chat/cli.py <agent_name> [--url http://127.0.0.1:8420] [--session NAME] \
        [--key KEY] [--thinking normal|brief]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

import httpx


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _print_event(event_type: str, data: dict[str, Any], last_type: str | None) -> str:
    """Print one SSE event, timestamped. Returns the event type, so the
    caller can track streaming-run continuity across calls."""
    if event_type in ("delta", "thinking_delta"):
        label = "ANSWER" if event_type == "delta" else "THINK "
        if last_type != event_type:
            print()
            print(f"[{_ts()}] {label}: ", end="", flush=True)
        print(data["text"], end="", flush=True)
        return event_type

    if last_type in ("delta", "thinking_delta"):
        print()  # close off the previous streaming line before a discrete event

    if event_type == "tool_call":
        print(f"[{_ts()}] TOOL_CALL: {data['name']} {json.dumps(data['arguments'])}")
    elif event_type == "tool_result":
        status = f"ERROR: {data['error']}" if data.get("error") else "ok"
        print(f"[{_ts()}] TOOL_RESULT: {data['tool_call_id']} -> {status}")
    elif event_type == "budget":
        print(f"[{_ts()}] BUDGET: {data['summary']}")
    elif event_type == "thrash_warning":
        print(f"[{_ts()}] THRASH_WARNING: {data['tool']} - {data['detail']}")
    elif event_type == "approval_needed":
        print(f"[{_ts()}] APPROVAL_NEEDED: {data}")
    elif event_type == "heartbeat":
        print(f"[{_ts()}] heartbeat")
    elif event_type == "done":
        print(f"[{_ts()}] DONE: verified={data.get('verified')} detail={data.get('detail')}")
        print(f"           budget:  {data.get('budget_summary')}")
        print(f"           session: {data.get('session_id')} ({data.get('session_name')})")
        # The only place the answer appears at all when the agent's config
        # doesn't set stream: true — no delta events fire in that case.
        final_text = data.get("final_text")
        if final_text:
            print(f"           final_text: {final_text}")
    elif event_type == "error":
        print(f"[{_ts()}] ERROR: {data['message']}")
    return event_type


_BRIEF_THINKING_PREFIX = "(Keep your thinking brief, just 2-3 sentences, then answer.) "


def _run_once(base_url: str, agent: str, session_name: str, headers: dict[str, str], message: str) -> None:
    print(f"[{_ts()}] >>> POST /agents/{agent}/runs")
    last_type: str | None = None
    with httpx.stream(
        "POST",
        f"{base_url}/agents/{agent}/runs",
        json={"message": message, "session_name": session_name},
        headers=headers,
        timeout=600.0,
    ) as resp:
        run_id = resp.headers.get("X-Run-Id", "?")
        print(f"[{_ts()}] <<< HTTP {resp.status_code}  run_id={run_id}")
        if resp.status_code != 200:
            print(resp.read().decode(errors="replace"))
            return
        current_type: str | None = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_type = line[len("event: "):]
            elif line.startswith("data: ") and current_type is not None:
                data = json.loads(line[len("data: "):])
                last_type = _print_event(current_type, data, last_type)
    if last_type in ("delta", "thinking_delta"):
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plain-terminal diagnostic client for agent-harness serve")
    parser.add_argument("agent", help="Agent name")
    parser.add_argument("--url", default="http://127.0.0.1:8420")
    parser.add_argument("--session", default="cli-debug", help="Session name to reuse across turns")
    parser.add_argument("--key", default=None, help="X-API-Key, if the server requires one")
    parser.add_argument(
        "--thinking", choices=["normal", "brief"], default="normal",
        help=(
            "'brief' prepends an instruction asking the model to keep its "
            "thinking short. This is a prompt-level trick, not a real "
            "reasoning-effort control — verified empirically that this "
            "model (qwen3-4b-thinking) ignores reasoning_effort, "
            "chat_template_kwargs.enable_thinking, and /no_think entirely; "
            "LM Studio's own log confirms it has no custom reasoning field "
            "to map those onto. This is the one thing that measurably "
            "helped (roughly halves reasoning tokens, confirmed across "
            "repeated runs) — not a substitute for a real effort dial."
        ),
    )
    args = parser.parse_args()

    headers = {"X-API-Key": args.key} if args.key else {}

    print(f"Connected to {args.url}, agent={args.agent}, session={args.session}, thinking={args.thinking}")
    print("Type a message and press Enter. Ctrl-C to quit.\n")
    try:
        while True:
            try:
                message = input("> ")
            except EOFError:
                break
            if not message.strip():
                continue
            if args.thinking == "brief":
                message = _BRIEF_THINKING_PREFIX + message
            _run_once(args.url, args.agent, args.session, headers, message)
            print()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
