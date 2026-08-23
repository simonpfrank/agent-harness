"""Minimal Streamlit chat client for the agent-harness HTTP API.

A quick way to try `agent-harness serve` interactively — not the
production chat UI the roadmap describes as its own separate project.

Run the server first:  agent-harness serve
Then:                   streamlit run chat/app.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import streamlit as st


def _handle_event(
    event_type: str, data: dict[str, Any], status: Any, show_thinking: bool, run_id: str, result: dict[str, Any],
) -> str | None:
    """Update `status`/`result` for one SSE event.

    Returns "delta" if the caller should yield `data["text"]` into the
    streamed answer, "stop" if the caller should stop reading, else None.
    """
    if event_type == "delta":
        return "delta"
    if event_type == "thinking_delta" and show_thinking:
        # Each event is one small fragment (a word or two) — accumulate
        # them, don't just display the latest one, or it looks like the
        # thinking text is replacing itself instead of growing.
        result["thinking_text"] = result.get("thinking_text", "") + data["text"]
        status.caption(f"🤔 {result['thinking_text'][-300:]}")
    elif event_type == "tool_call":
        status.caption(f"🔧 calling `{data['name']}`…")
    elif event_type == "tool_result":
        status.caption(f"❌ {data['error']}" if data.get("error") else f"✅ `{data['tool_call_id']}` done")
    elif event_type == "budget":
        status.caption(data["summary"])
    elif event_type == "thrash_warning":
        st.warning(f"Thrashing on {data['tool']}: {data['detail']}")
    elif event_type == "approval_needed":
        result["approval"] = {"run_id": run_id, **data}
        return "stop"
    elif event_type == "error":
        result["error"] = data["message"]
        return "stop"
    elif event_type == "done":
        result["final_text"] = data.get("final_text") or ""
        return "stop"
    return None


st.set_page_config(page_title="Agent Harness Chat", page_icon="💬")

with st.sidebar:
    st.header("Connection")
    base_url = st.text_input("Server URL", value="http://127.0.0.1:8420").rstrip("/")
    api_key = st.text_input("API key (optional)", type="password")
    show_thinking = st.checkbox("Show thinking", value=False)
    headers = {"X-API-Key": api_key} if api_key else {}

    agent_names: list[str] = []
    try:
        resp = httpx.get(f"{base_url}/agents", headers=headers, timeout=5.0)
        resp.raise_for_status()
        agent_names = resp.json()["agents"]
    except httpx.HTTPError as exc:
        st.error(f"Can't reach server: {exc}")

    agent_name = st.selectbox("Agent", agent_names) if agent_names else None

    if "session_name" not in st.session_state:
        st.session_state.session_name = f"streamlit-{uuid.uuid4().hex[:8]}"
    st.text_input("Session name", key="session_name")
    st.caption(
        "No history endpoint yet — switching to an existing name starts "
        "this UI empty even though the server remembers it.",
    )

    if st.button("New session"):
        st.session_state.session_name = f"streamlit-{uuid.uuid4().hex[:8]}"
        st.session_state.messages = []
        st.rerun()

st.title("💬 Agent Harness Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Message the agent...", disabled=agent_name is None)

if prompt and agent_name:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status = st.empty()
        result: dict[str, Any] = {"final_text": None, "approval": None, "error": None}

        def event_stream() -> Any:
            try:
                with httpx.stream(
                    "POST",
                    f"{base_url}/agents/{agent_name}/runs",
                    json={"message": prompt, "session_name": st.session_state.session_name},
                    headers=headers,
                    timeout=120.0,
                ) as resp:
                    if resp.status_code != 200:
                        result["error"] = f"HTTP {resp.status_code}: {resp.read().decode(errors='replace')}"
                        return
                    run_id = resp.headers.get("X-Run-Id", "?")
                    current_type: str | None = None
                    for line in resp.iter_lines():
                        if line.startswith("event: "):
                            current_type = line[len("event: "):]
                        elif line.startswith("data: ") and current_type is not None:
                            data = json.loads(line[len("data: "):])
                            handled = _handle_event(current_type, data, status, show_thinking, run_id, result)
                            if handled == "delta":
                                yield data["text"]
                            if handled == "stop":
                                return
            except httpx.HTTPError as exc:
                result["error"] = f"Connection failed: {exc}"

        final_text = st.write_stream(event_stream)
        status.empty()

        if result["error"]:
            st.error(result["error"])
        elif result["approval"]:
            a = result["approval"]
            target = a.get("tool_name") or a.get("domain") or "plan"
            st.warning(
                f"⚠️ Approval needed — **{a['kind']}**: `{target}`\n\n"
                "This simple client doesn't answer approvals live (needs a background "
                "connection outside Streamlit's rerun model). Answer manually:\n\n"
                f"```bash\ncurl -X POST {base_url}/runs/{a['run_id']}/signal "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"approval_id\": \"{a['approval_id']}\", \"decision\": \"allow_once\"}}'\n```"
            )
        else:
            text = result["final_text"] if result["final_text"] is not None else final_text
            st.session_state.messages.append({"role": "assistant", "content": text or ""})
