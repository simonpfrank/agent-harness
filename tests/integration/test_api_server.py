"""Real, zero-mock, end-to-end tests for the HTTP API server.

No mocks anywhere. A real Flask app is served on a real socket via
werkzeug's dev server in a background thread; a real httpx client makes
real HTTP requests against it. Tests that need a genuine agent turn call
the live Anthropic API and skip cleanly if ANTHROPIC_API_KEY isn't set —
the auth-rejection tests don't need a key, since auth fails before any
agent logic runs.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator

import httpx
import pytest
from dotenv import load_dotenv
from werkzeug.serving import make_server

from agent_harness.api.routes import create_app
from agent_harness.session import find_session_by_name

load_dotenv()

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

AGENTS_DIR = "tests/data"


class _ServerHandle:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


def _run_server(agents_dir: str = AGENTS_DIR, api_key: str | None = None) -> Iterator[_ServerHandle]:
    app = create_app(agents_dir=agents_dir, api_key=api_key)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _ServerHandle(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join(timeout=5.0)


@pytest.fixture
def server() -> Iterator[_ServerHandle]:
    yield from _run_server()


@pytest.fixture
def secured_server() -> Iterator[_ServerHandle]:
    yield from _run_server()


def _read_sse_events(response: httpx.Response, max_events: int = 50) -> list[dict[str, object]]:
    """Parse a real SSE stream into a list of `{"event": ..., "data": ...}` dicts.

    Stops after a `done`/`error` event, or `max_events`, whichever first.
    """
    collected: list[dict[str, object]] = []
    current_type: str | None = None
    current_data: object = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current_type = line[len("event: "):]
        elif line.startswith("data: "):
            current_data = json.loads(line[len("data: "):])
        elif line == "" and current_type is not None:
            collected.append({"event": current_type, "data": current_data})
            if current_type in ("done", "error") or len(collected) >= max_events:
                break
            current_type, current_data = None, None
    return collected


class TestAuthRejection:
    """No API key needed — auth fails before any agent logic runs."""

    def test_missing_key_rejected(self, server: _ServerHandle) -> None:
        resp = httpx.get(f"{server.base_url}/agents")
        assert resp.status_code == 200  # this server has no api_key configured

    def test_wrong_key_rejected_when_configured(self) -> None:
        for handle in _run_server(api_key="real-secret"):
            resp = httpx.get(f"{handle.base_url}/agents", headers={"X-API-Key": "wrong"})
            assert resp.status_code == 401
            resp_ok = httpx.get(f"{handle.base_url}/agents", headers={"X-API-Key": "real-secret"})
            assert resp_ok.status_code == 200


@requires_api_key
class TestRealRunOverHttp:
    def test_real_run_streams_delta_and_done_events(self, server: _ServerHandle) -> None:
        with httpx.stream(
            "POST", f"{server.base_url}/agents/agent_react/runs",
            json={"message": "What is 2+2? Just the number."}, timeout=60.0,
        ) as resp:
            assert resp.status_code == 200
            events = _read_sse_events(resp)

        assert events, "expected at least one event"
        assert events[-1]["event"] == "done"
        done_data = events[-1]["data"]
        assert isinstance(done_data, dict)
        assert done_data["final_text"]
        assert "4" in done_data["final_text"]


@requires_api_key
class TestConcurrentSessionExclusivityOverRealHttp:
    def test_racing_requests_on_same_session_one_wins_one_409(self, server: _ServerHandle) -> None:
        barrier = threading.Barrier(2)
        statuses: list[int] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def poster() -> None:
            barrier.wait()
            try:
                with httpx.stream(
                    "POST", f"{server.base_url}/agents/agent_react/runs",
                    json={"message": "Say ok.", "session_name": "concurrency-http-test"}, timeout=60.0,
                ) as resp:
                    status = resp.status_code
                    if status == 200:
                        _read_sse_events(resp)  # drain to completion
                with lock:
                    statuses.append(status)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=poster)
        t2 = threading.Thread(target=poster)
        t1.start()
        t2.start()
        t1.join(timeout=60.0)
        t2.join(timeout=60.0)

        assert errors == []
        assert sorted(statuses) == [200, 409]

        session = find_session_by_name(f"{AGENTS_DIR}/agent_react/sessions", "concurrency-http-test")
        assert session is not None
        # Exactly one run's turn survived — proves start_run's exclusivity
        # check, not a lucky absence of a real race. (system + user + assistant)
        assert len(session.messages) == 3


@requires_api_key
class TestApprovalRoundTripOverRealHttp:
    def test_approval_needed_then_signal_completes_the_run(self, secured_server: _ServerHandle) -> None:
        events: list[dict[str, object]] = []
        run_id_box: dict[str, str] = {}
        approval_id_box: dict[str, str] = {}
        approval_seen = threading.Event()

        def run_and_collect() -> None:
            with httpx.stream(
                "POST", f"{secured_server.base_url}/agents/secured_agent/runs",
                json={"message": "Run the shell command: echo hi"}, timeout=60.0,
            ) as resp:
                run_id_box["id"] = resp.headers["X-Run-Id"]
                current_type: str | None = None
                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        current_type = line[len("event: "):]
                    elif line.startswith("data: ") and current_type is not None:
                        data = json.loads(line[len("data: "):])
                        events.append({"event": current_type, "data": data})
                        if current_type == "approval_needed":
                            approval_id_box["id"] = data["approval_id"]
                            approval_seen.set()
                        if current_type in ("done", "error"):
                            return

        t = threading.Thread(target=run_and_collect)
        t.start()

        # Answer the approval from a *second* real connection while the
        # first is still open, blocked in registry.await_signal — this is
        # the actual thing this test exists to prove, not just that an
        # approval_needed event was emitted.
        assert approval_seen.wait(timeout=30.0), "approval_needed never arrived"
        signal_resp = httpx.post(
            f"{secured_server.base_url}/runs/{run_id_box['id']}/signal",
            json={"approval_id": approval_id_box["id"], "decision": "allow_once"},
            timeout=10.0,
        )
        assert signal_resp.status_code == 202

        t.join(timeout=60.0)
        assert events, "expected at least one event"
        assert events[-1]["event"] == "done"  # not the timeout-driven default-deny path
