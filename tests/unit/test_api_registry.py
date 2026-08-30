"""Tests for agent_harness.api.registry.

Single-threaded correctness tests first, then real concurrency proofs using
the same threading.Thread + threading.Barrier + errors-sink convention
established in tests/integration/test_concurrency_safety.py — no mocks.
"""

import threading
import time

import pytest

from agent_harness.api.events import SseEvent
from agent_harness.api.registry import RunRegistry, SessionBusyError, UnknownRunError

_N_THREADS = 20


class TestStartRunEndRun:
    def test_start_run_claims_session(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")  # must not raise

    def test_second_start_on_same_session_raises_session_busy(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        with pytest.raises(SessionBusyError):
            registry.start_run("run-2", "session-1")

    def test_different_sessions_do_not_conflict(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        registry.start_run("run-2", "session-2")  # must not raise

    def test_end_run_releases_session_for_reuse(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        registry.end_run("run-1")
        registry.start_run("run-2", "session-1")  # must not raise

    def test_end_run_on_unknown_run_is_a_no_op(self) -> None:
        registry = RunRegistry()
        registry.end_run("never-started")  # must not raise


class TestCancellation:
    def test_defaults_to_not_cancelled(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        assert registry.is_cancelled("run-1") is False

    def test_request_cancel_sets_the_flag(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        registry.request_cancel("run-1")
        assert registry.is_cancelled("run-1") is True

    def test_request_cancel_on_unknown_run_is_a_no_op(self) -> None:
        registry = RunRegistry()
        registry.request_cancel("never-started")  # must not raise

    def test_is_cancelled_on_unknown_run_defaults_to_false(self) -> None:
        registry = RunRegistry()
        assert registry.is_cancelled("never-started") is False

    def test_cancel_on_one_run_does_not_affect_another(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        registry.start_run("run-2", "session-2")
        registry.request_cancel("run-1")
        assert registry.is_cancelled("run-1") is True
        assert registry.is_cancelled("run-2") is False


class TestConcurrentCancellation:
    def test_cancel_from_another_thread_is_seen_promptly(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        seen: list[bool] = []

        def poller() -> None:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if registry.is_cancelled("run-1"):
                    seen.append(True)
                    return
                time.sleep(0.01)
            seen.append(False)

        thread = threading.Thread(target=poller)
        thread.start()
        time.sleep(0.05)
        registry.request_cancel("run-1")
        thread.join(timeout=2.0)

        assert seen == [True]


class TestEventQueue:
    def test_push_then_pop_round_trip(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        event = SseEvent(event="delta", data={"text": "hi"}, seq=1)
        registry.push_event("run-1", event)
        popped = registry.pop_event("run-1", timeout=1.0)
        assert popped is event

    def test_pop_times_out_to_none_not_an_exception(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        popped = registry.pop_event("run-1", timeout=0.05)
        assert popped is None

    def test_push_to_unknown_run_raises(self) -> None:
        registry = RunRegistry()
        with pytest.raises(UnknownRunError):
            registry.push_event("never-started", SseEvent(event="delta", data={}, seq=1))

    def test_pop_from_unknown_run_raises(self) -> None:
        registry = RunRegistry()
        with pytest.raises(UnknownRunError):
            registry.pop_event("never-started", timeout=0.05)


class TestTryPushEvent:
    """A reader can disconnect (Ctrl-C, cancellation making an abandoned
    run finish fast, a plain dropped connection) at any point while its
    worker thread is still mid-execution — every subsequent push from that
    worker must tolerate the run having already been unregistered, not
    crash the whole worker thread."""

    def test_returns_true_and_enqueues_for_a_known_run(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        event = SseEvent(event="delta", data={"text": "hi"}, seq=1)
        assert registry.try_push_event("run-1", event) is True
        assert registry.pop_event("run-1", timeout=1.0) is event

    def test_returns_false_for_an_unknown_run_without_raising(self) -> None:
        registry = RunRegistry()
        result = registry.try_push_event("never-started", SseEvent(event="delta", data={}, seq=1))
        assert result is False


class TestApprovalSignal:
    def test_resolve_wakes_a_waiting_await(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        results: list[dict[str, object] | None] = []

        def waiter() -> None:
            results.append(registry.await_signal("run-1", "approval-1", timeout=2.0))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)  # give the waiter time to register before resolving
        registry.resolve_signal("run-1", "approval-1", {"decision": "allow_once"})
        t.join(timeout=2.0)

        assert results == [{"decision": "allow_once"}]

    def test_await_times_out_to_none(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        result = registry.await_signal("run-1", "approval-1", timeout=0.05)
        assert result is None

    def test_resolve_unknown_approval_raises(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        with pytest.raises(UnknownRunError):
            registry.resolve_signal("run-1", "no-such-approval", {"decision": "deny"})

    def test_resolve_on_unknown_run_raises(self) -> None:
        registry = RunRegistry()
        with pytest.raises(UnknownRunError):
            registry.resolve_signal("never-started", "approval-1", {"decision": "deny"})


class TestConcurrentSessionExclusivity:
    def test_racing_start_run_on_same_session_exactly_one_wins(self) -> None:
        registry = RunRegistry()
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []
        succeeded: list[str] = []
        lock = threading.Lock()

        def racer(idx: int) -> None:
            barrier.wait()
            try:
                registry.start_run(f"run-{idx}", "shared-session")
                with lock:
                    succeeded.append(f"run-{idx}")
            except SessionBusyError:
                pass
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=racer, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(succeeded) == 1  # exactly one racer claimed the session

    def test_distinct_sessions_never_conflict_under_real_concurrency(self) -> None:
        registry = RunRegistry()
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []

        def worker(idx: int) -> None:
            barrier.wait()
            try:
                registry.start_run(f"run-{idx}", f"session-{idx}")
                registry.end_run(f"run-{idx}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


class TestConcurrentApprovalSignal:
    def test_blocked_waiter_unblocked_by_concurrent_resolver(self) -> None:
        registry = RunRegistry()
        registry.start_run("run-1", "session-1")
        barrier = threading.Barrier(2)
        results: list[dict[str, object] | None] = []
        errors: list[BaseException] = []

        def waiter() -> None:
            barrier.wait()
            try:
                results.append(registry.await_signal("run-1", "approval-1", timeout=2.0))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def resolver() -> None:
            barrier.wait()
            time.sleep(0.05)  # ensure the waiter is registered first
            try:
                registry.resolve_signal("run-1", "approval-1", {"decision": "allow_once"})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=waiter)
        t2 = threading.Thread(target=resolver)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        assert errors == []
        assert results == [{"decision": "allow_once"}]
