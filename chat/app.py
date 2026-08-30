"""Minimal Streamlit chat client for the agent-harness HTTP API.

A quick way to try `agent-harness serve` interactively — not the
production chat UI the roadmap describes as its own separate project.

Run the server first:  agent-harness serve
Then:                   streamlit run chat/app.py
"""

from __future__ import annotations

import contextlib
import json
import threading
import uuid
from typing import Any

import httpx
import streamlit as st


def _handle_event(
    event_type: str, data: dict[str, Any], show_thinking: bool, active: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Update `active` for one SSE event. Caller must hold `active["lock"]`.

    Returns `(action, status_line)`: `action` is `"stop"` if the caller
    should stop reading, else `None`. `status_line` is new transient status
    text to show, or `None` to leave the current one unchanged.
    """
    if event_type == "delta":
        active["text"] = active.get("text", "") + data["text"]
        return None, None
    if event_type == "thinking_delta" and show_thinking:
        # Each event is one small fragment (a word or two) — accumulate
        # them, don't just display the latest one, or it looks like the
        # thinking text is replacing itself instead of growing.
        active["thinking_text"] = active.get("thinking_text", "") + data["text"]
        return None, f"🤔 {active['thinking_text']}"
    if event_type == "tool_call":
        active.setdefault("tool_calls", {})[data["id"]] = {
            "name": data["name"], "arguments": data["arguments"], "output": None, "error": None,
        }
        args_preview = ", ".join(f"{k}={v!r}" for k, v in data["arguments"].items())
        return None, f"🔧 `{data['name']}({args_preview})`…"
    if event_type == "tool_result":
        record = active["tool_calls"][data["tool_call_id"]]
        record["output"] = data.get("output")
        record["error"] = data.get("error")
        if record["error"]:
            return None, f"❌ {record['error']}"
        output = (record["output"] or "").strip()
        preview = output[:500] + ("…" if len(output) > 500 else "")
        return None, f"✅ {preview}" if preview else "✅ done"
    if event_type == "budget":
        return None, data["summary"]
    if event_type == "thrash_warning":
        active["thrash_warning"] = f"Thrashing on {data['tool']}: {data['detail']}"
        return None, None
    if event_type == "approval_needed":
        active["approval"] = {"run_id": active.get("run_id"), **data}
        return "stop", None
    if event_type == "error":
        active["error"] = data["message"]
        return "stop", None
    if event_type in ("done", "cancelled"):
        active["final_text"] = data.get("final_text") or ""
        active["was_cancelled"] = event_type == "cancelled"
        return "stop", None
    return None, None


def _render_details(container: Any, msg: dict[str, Any]) -> None:
    """Render an assistant turn's thinking/tool-call detail as collapsed
    expanders — kept around after the turn finishes so they can be
    studied later, rather than vanishing once the answer arrives."""
    if msg.get("thinking"):
        with container.expander("🤔 Thinking"):
            st.markdown(msg["thinking"])
    for tc in msg.get("tool_calls", []):
        label = f"❌ {tc['name']}" if tc.get("error") else f"🔧 {tc['name']}"
        with container.expander(label):
            st.code(json.dumps(tc["arguments"], indent=2), language="json")
            if tc.get("error"):
                st.error(tc["error"])
            elif tc.get("output"):
                st.text(tc["output"])


def _new_active_run(base_url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Shared state a background thread writes into and the live-run
    fragment reads from.

    Never touch `st.session_state` itself from the background thread —
    only mutate this plain dict (safe cross-thread, unlike assigning into
    `st.session_state`, which must happen on the main script thread).
    """
    return {
        "lock": threading.Lock(),
        "base_url": base_url,
        "headers": headers,
        "run_id": None,
        "text": "",
        "thinking_text": "",
        "status_line": "",
        "tool_calls": {},
        "done": False,
        "error": None,
        "approval": None,
        "final_text": None,
        "was_cancelled": False,
    }


def _stream_worker(
    base_url: str, agent: str, session_name: str, headers: dict[str, str], message: str,
    show_thinking: bool, active: dict[str, Any],
) -> None:
    """Runs on a background thread — must never call any `st.*` function."""
    try:
        with httpx.stream(
            "POST",
            f"{base_url}/agents/{agent}/runs",
            json={"message": message, "session_name": session_name},
            headers=headers,
            timeout=600.0,
        ) as resp:
            with active["lock"]:
                active["run_id"] = resp.headers.get("X-Run-Id", "?")
            if resp.status_code != 200:
                with active["lock"]:
                    active["error"] = f"HTTP {resp.status_code}: {resp.read().decode(errors='replace')}"
                return
            current_type: str | None = None
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    current_type = line[len("event: "):]
                elif line.startswith("data: ") and current_type is not None:
                    data = json.loads(line[len("data: "):])
                    with active["lock"]:
                        action, status_line = _handle_event(current_type, data, show_thinking, active)
                        if status_line is not None:
                            active["status_line"] = status_line
                    if action == "stop":
                        break
    except httpx.HTTPError as exc:
        with active["lock"]:
            active["error"] = f"Connection failed: {exc}"
    finally:
        with active["lock"]:
            active["done"] = True


def _send_cancel(base_url: str, run_id: str | None, headers: dict[str, str]) -> None:
    """Best-effort: swallows its own connection errors."""
    if not run_id or run_id == "?":
        return
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(f"{base_url}/runs/{run_id}/signal", json={"type": "cancel"}, headers=headers, timeout=5.0)


@st.fragment(run_every="0.2s")
def _live_run(base_url: str, agent_name: str | None, headers: dict[str, str], show_thinking: bool) -> None:
    """Owns the entire bottom bar (plain input, or disabled input + Stop
    button) as well as the in-flight turn's display, ticking independently
    of the main script so the button stays clickable while a background
    thread is still streaming — `st.write_stream` blocked the whole script,
    which made a Stop button unclickable until the stream finished on its
    own.

    Must be the *only* writer of `st.bottom` in the whole app: the main
    script body used to also write a plain `st.chat_input` into `st.bottom`
    on the script run where a prompt was first submitted (before
    `active_run` existed yet), then this fragment wrote its own version of
    `st.bottom` moments later in that same run — Streamlit doesn't replace
    one write with the other, it stacks them, confirmed live as two visibly
    duplicated input rows for the entire run. Funneling every `st.bottom`
    write through this one fragment avoids that.

    Idle cost when nothing is running: one cheap no-op tick every 0.2s,
    accepted as the simplest option for a diagnostic client.
    """
    active = st.session_state.get("active_run")

    if active is None:
        with st.bottom:
            prompt = st.chat_input("Message the agent...", disabled=agent_name is None)
        if prompt and agent_name:
            st.session_state.messages.append({"role": "user", "content": prompt})
            new_active = _new_active_run(base_url, headers)
            st.session_state.active_run = new_active
            threading.Thread(
                target=_stream_worker,
                args=(base_url, agent_name, st.session_state.session_name, headers, prompt, show_thinking, new_active),
                daemon=True,
            ).start()
            # Full app rerun, not just this fragment: the user bubble is drawn by
            # the main script's history loop, which a fragment's own auto-ticks
            # never re-execute — without this the bubble would render once here
            # and then vanish on the very next 0.2s tick, when this fragment's
            # region gets replaced wholesale by the "active is not None" branch
            # below (confirmed live: the user's own message flashed then disappeared).
            st.rerun()
        return

    with active["lock"]:
        snapshot = {k: v for k, v in active.items() if k != "lock"}

    with st.chat_message("assistant"):
        if snapshot["status_line"] and not snapshot["done"]:
            st.caption(snapshot["status_line"])
        if snapshot["text"]:
            st.markdown(snapshot["text"])

        if not snapshot["done"]:
            with st.bottom:
                input_col, stop_col = st.columns([8, 1])
                with input_col:
                    st.chat_input("Message the agent...", disabled=True)
                with stop_col:
                    if snapshot["run_id"] and st.button("⏹", help="Stop", key="stop_button"):
                        _send_cancel(snapshot["base_url"], snapshot["run_id"], snapshot["headers"])
            return

        if snapshot["error"]:
            st.error(snapshot["error"])
        elif snapshot["approval"]:
            a = snapshot["approval"]
            target = a.get("tool_name") or a.get("domain") or "plan"
            st.warning(
                f"⚠️ Approval needed — **{a['kind']}**: `{target}`\n\n"
                "This simple client doesn't answer approvals live (needs a background "
                "connection outside Streamlit's rerun model). Answer manually:\n\n"
                f"```bash\ncurl -X POST {snapshot['base_url']}/runs/{a['run_id']}/signal "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"approval_id\": \"{a['approval_id']}\", \"decision\": \"allow_once\"}}'\n```"
            )
        else:
            text = snapshot["final_text"] if snapshot["final_text"] is not None else snapshot["text"]
            if snapshot["was_cancelled"]:
                text = f"{text or ''}\n\n*⏹ stopped*"
            st.session_state.messages.append({
                "role": "assistant",
                "content": text or "",
                "thinking": snapshot["thinking_text"],
                "tool_calls": list(snapshot["tool_calls"].values()),
            })

    st.session_state.active_run = None
    st.rerun()


st.set_page_config(page_title="Agent Harness Chat", page_icon="💬")

st.markdown(
    """
    <style>
    div[data-testid="stHorizontalBlock"]:has(.st-key-stop_button) {
        align-items: stretch;
    }
    .st-key-stop_button {
        display: flex;
        height: 100%;
    }
    .st-key-stop_button button {
        border-color: #ff4b4b;
        color: #ff4b4b;
        height: 100%;
        width: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
        st.session_state.active_run = None
        st.rerun()

st.title("💬 Agent Harness Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_run" not in st.session_state:
    st.session_state.active_run = None

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            _render_details(st.container(), msg)
        st.markdown(msg["content"])

_live_run(base_url, agent_name, headers, show_thinking)
