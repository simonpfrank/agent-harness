"""Flask test-client wiring tests for agent_harness.api.routes.

Wiring correctness only (auth, routing, request validation) — a real,
zero-mock end-to-end run over a real socket (streaming, approvals,
genuine concurrency) is tests/integration/test_api_server.py's job.
"""

import threading
import time
from unittest.mock import MagicMock, patch

from agent_harness.api.events import SseEvent
from agent_harness.api.registry import RunRegistry
from agent_harness.api.routes import _sse_stream, create_app

AGENTS_DIR = "tests/data"


class TestAuth:
    def test_missing_key_rejected_with_401(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR, api_key="secret")
        client = app.test_client()
        resp = client.get("/agents")
        assert resp.status_code == 401

    def test_wrong_key_rejected_with_401(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR, api_key="secret")
        client = app.test_client()
        resp = client.get("/agents", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_accepted(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR, api_key="secret")
        client = app.test_client()
        resp = client.get("/agents", headers={"X-API-Key": "secret"})
        assert resp.status_code == 200

    def test_no_configured_key_means_no_auth_enforced(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR, api_key=None)
        client = app.test_client()
        resp = client.get("/agents")
        assert resp.status_code == 200


class TestListAgents:
    def test_returns_known_agent_names(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.get("/agents")
        assert resp.status_code == 200
        assert "valid_agent" in resp.get_json()["agents"]


class TestStartRunValidation:
    def test_unknown_agent_returns_404(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.post("/agents/no-such-agent/runs", json={"message": "hi"})
        assert resp.status_code == 404

    def test_missing_message_returns_400(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.post("/agents/valid_agent/runs", json={})
        assert resp.status_code == 400

    def test_malformed_config_yaml_returns_400_with_message_not_a_raw_500(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.post("/agents/invalid_agent_bad_yaml/runs", json={"message": "hi"})
        assert resp.status_code == 400
        assert "invalid_agent_bad_yaml" in resp.get_json()["error"]

    def test_session_already_busy_returns_409(self) -> None:
        registry = RunRegistry()
        registry.start_run("already-running", "busy-session")
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()
        resp = client.post(
            "/agents/valid_agent/runs", json={"message": "hi", "session_id": "busy-session"},
        )
        assert resp.status_code == 409

    def test_exclusivity_keyed_on_requested_name_not_resolved_session_id(self) -> None:
        """Regression test: exclusivity must be claimed on the caller's
        requested session_name *before* any find-or-create file lookup —
        keying on the resolved Session's id would let two concurrent
        first-time requests for the same never-before-seen name each
        create a distinct fresh id and never collide. Caught by a real
        two-thread HTTP test in tests/integration/test_api_server.py;
        this is the fast, deterministic version of the same assertion."""
        registry = RunRegistry()
        registry.start_run("already-running", "brand-new-name")  # simulates a first request mid-flight
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()
        resp = client.post(
            "/agents/valid_agent/runs", json={"message": "hi", "session_name": "brand-new-name"},
        )
        assert resp.status_code == 409


class TestStartRunResponseHeaders:
    def test_session_busy_response_has_no_run_id_header(self) -> None:
        # Sanity check the header is specific to a successfully-started run,
        # not present on every response from this endpoint.
        registry = RunRegistry()
        registry.start_run("already-running", "busy-session")
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()
        resp = client.post(
            "/agents/valid_agent/runs", json={"message": "hi", "session_id": "busy-session"},
        )
        assert "X-Run-Id" not in resp.headers


class TestSignalValidation:
    def test_missing_fields_returns_400(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.post("/runs/some-run/signal", json={})
        assert resp.status_code == 400

    def test_unknown_run_returns_404(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        resp = client.post(
            "/runs/no-such-run/signal", json={"approval_id": "a1", "decision": "deny"},
        )
        assert resp.status_code == 404

    def test_known_pending_signal_returns_202_and_wakes_the_waiter(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        results: list[dict[str, object] | None] = []

        def waiter() -> None:
            results.append(registry.await_signal("run-1", "a1", timeout=2.0))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)  # give the waiter time to register before signaling

        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()
        resp = client.post(
            "/runs/run-1/signal", json={"approval_id": "a1", "decision": "allow_once"},
        )
        assert resp.status_code == 202
        t.join(timeout=2.0)
        assert results == [{"decision": "allow_once"}]


class TestWorkerFailureSafety:
    """A failure deep in the background worker (not just the known
    RuntimeError-from-a-provider-call case) must still reach the client as
    a real `error` event and release the session lock — not hang forever
    on heartbeats with the session stuck busy."""

    def test_unexpected_worker_failure_reaches_client_as_error_event(self) -> None:
        app = create_app(agents_dir=AGENTS_DIR)
        client = app.test_client()
        # invalid_agent_bad_provider loads fine (valid YAML) but fails
        # prepare_runtime's validate_config deep inside the worker thread —
        # a failure this build previously had zero handling for at all.
        resp = client.post(
            "/agents/invalid_agent_bad_provider/runs",
            json={"message": "hi", "session_name": "worker-failure-test"},
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "event: error" in body
        assert "fakellm" in body

    def test_session_lock_released_after_worker_failure(self) -> None:
        registry = RunRegistry()
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()
        first = client.post(
            "/agents/invalid_agent_bad_provider/runs",
            json={"message": "hi", "session_name": "worker-failure-release-test"},
        )
        first.get_data()  # drain to completion — worker must finish and release the lock

        second = client.post(
            "/agents/invalid_agent_bad_provider/runs",
            json={"message": "hi", "session_name": "worker-failure-release-test"},
        )
        assert second.status_code == 200  # not 409 — proves end_run() fired after the crash
        second.get_data()


class TestDoubleTerminalEventBug:
    """Real bug found live: a RuntimeError during run_messages() correctly
    pushed an `error` event — but the reader ends the run and removes it
    from the registry the moment it sees ANY terminal event, so the code
    that ran afterward (trying to also push `done`) always raised
    UnknownRunError, crashing the worker thread instead of ending cleanly."""

    def test_runtime_error_produces_exactly_one_terminal_event_not_a_crash(self) -> None:
        registry = RunRegistry()
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()

        fake_runtime = MagicMock()
        fake_runtime.init_messages.return_value = []
        fake_runtime.run_messages.side_effect = RuntimeError("boom")
        fake_runtime.budget.summary.return_value = "Turn 1/10 | $0.00/$0.10"

        with patch("agent_harness.api.routes.prepare_runtime", return_value=fake_runtime):
            resp = client.post(
                "/agents/valid_agent/runs", json={"message": "hi", "session_name": "double-terminal-test"},
            )
            body = resp.get_data(as_text=True)

        assert body.count("event: error") == 1
        assert "event: done" not in body
        assert "boom" in body
        # finalize() runs on the worker thread, slightly after the reader
        # thread returns — poll briefly rather than assert immediately.
        for _ in range(20):
            if fake_runtime.finalize.called:
                break
            time.sleep(0.05)
        fake_runtime.finalize.assert_called_once()  # cleanup still runs after an error

    def test_session_lock_released_after_runtime_error(self) -> None:
        registry = RunRegistry()
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()

        fake_runtime = MagicMock()
        fake_runtime.init_messages.return_value = []
        fake_runtime.run_messages.side_effect = RuntimeError("boom")
        fake_runtime.budget.summary.return_value = "Turn 1/10 | $0.00/$0.10"

        with patch("agent_harness.api.routes.prepare_runtime", return_value=fake_runtime):
            first = client.post(
                "/agents/valid_agent/runs", json={"message": "hi", "session_name": "double-terminal-lock-test"},
            )
            first.get_data()

            second = client.post(
                "/agents/valid_agent/runs", json={"message": "hi", "session_name": "double-terminal-lock-test"},
            )
            assert second.status_code == 200  # not 409 — proves end_run() fired, no crash held the lock forever


class TestSessionLockReleasedWithoutAReader:
    """Real bug found live: `registry.end_run()` was only ever called by
    the code reading the SSE stream, when it saw a terminal event. But the
    worker thread runs independently of whether anyone is still reading —
    if the client vanishes (closed, network dropped, laptop hibernated)
    before consuming the terminal event, the worker finishes its job fine
    but nothing is left to release the session lock. Stuck forever, no
    relationship to timeouts — confirmed live: a session was still marked
    busy the next day after the reading client had long since gone."""

    def test_worker_releases_the_lock_even_if_nobody_ever_reads_the_stream(self) -> None:
        registry = RunRegistry()
        app = create_app(agents_dir=AGENTS_DIR, registry=registry)
        client = app.test_client()

        fake_runtime = MagicMock()
        fake_runtime.init_messages.return_value = []
        fake_runtime.run_messages.return_value = "the answer"
        fake_runtime.budget.summary.return_value = "Turn 1/10 | $0.00/$0.10"

        with patch("agent_harness.api.routes.prepare_runtime", return_value=fake_runtime):
            client.post(
                "/agents/valid_agent/runs", json={"message": "hi", "session_name": "abandoned-reader-test"},
            )
            # Deliberately never call .get_data() on the response — simulates a client
            # that vanished before consuming any part of the response body,
            # not even the first event.

            for _ in range(40):
                if registry._active_sessions.get("abandoned-reader-test") is None:  # noqa: SLF001
                    break
                time.sleep(0.05)

            second = client.post(
                "/agents/valid_agent/runs", json={"message": "hi", "session_name": "abandoned-reader-test"},
            )
            assert second.status_code == 200  # not 409 — the worker released the lock on its own


class TestImmediateFirstEvent:
    """Real gap found live: a client saw no response at all — not even
    HTTP headers — for as long as the model took to produce its first
    real token (measured up to 15s in one case). `_sse_stream`'s first
    action was `registry.pop_event(timeout=15.0)`, which blocks until
    something is pushed; nothing was written to the response before that
    resolved, so the WSGI layer had nothing to flush. Fixed: yield an
    immediate event before ever blocking, so the connection itself is
    never held hostage to how long the model takes."""

    def test_first_yielded_chunk_does_not_wait_for_the_heartbeat_interval(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        gen = _sse_stream(registry, "run-1")

        start = time.monotonic()
        first_chunk = next(gen)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0  # must not wait anywhere near the 15s heartbeat interval
        assert "event: heartbeat" in first_chunk

    def test_normal_event_flow_still_works_after_the_immediate_first_chunk(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        gen = _sse_stream(registry, "run-1")
        next(gen)  # the new immediate first chunk

        registry.push_event("run-1", SseEvent("delta", {"agent": "default", "text": "hi"}, 1))
        second_chunk = next(gen)
        assert "event: delta" in second_chunk
        assert '"text": "hi"' in second_chunk


class TestLockReleasedOnClientDisconnect:
    """A crashed/killed client (Ctrl-C, closed terminal, dropped network)
    tears its generator down via GeneratorExit — real Python behavior when
    a consumer stops iterating a generator early. Previously nothing
    caught this, so the session stayed locked until the abandoned run
    eventually finished on its own (the worker's own `finally: end_run`
    is the backstop, but that only fires once the underlying model call
    actually completes — could be minutes). This releases it immediately."""

    def test_disconnect_at_the_first_yield_releases_the_lock_immediately(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        gen = _sse_stream(registry, "run-1")
        next(gen)  # consume the immediate first heartbeat; suspended right there

        gen.close()  # simulates the WSGI server tearing the generator down

        registry.start_run("run-2", "session-1")  # would raise SessionBusyError if the lock were still held
