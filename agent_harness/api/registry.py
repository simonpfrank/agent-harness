"""In-flight run tracking: session exclusivity and approval-signal blocking.

One `RunRegistry` handles both concerns because they're the same shape of
problem — shared state keyed by an id, one side blocks, another side
signals — and splitting them into two separately-locked objects would make
"claim a session slot" and "register a run" non-atomic, a real race.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from agent_harness.api.events import SseEvent


class SessionBusyError(Exception):
    """Raised when a session already has an active run."""


class UnknownRunError(Exception):
    """Raised when an operation references a run or pending signal that
    isn't (or is no longer) registered."""


class _PendingSignal:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: dict[str, Any] | None = None


class _RunState:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.queue: queue.Queue[SseEvent] = queue.Queue()
        self.pending: dict[str, _PendingSignal] = {}
        self.cancel_event = threading.Event()


class RunRegistry:
    """Tracks in-flight runs: which session each owns, its event queue, and
    any approval signals it's currently waiting on."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_sessions: dict[str, str] = {}
        self._runs: dict[str, _RunState] = {}

    def start_run(self, run_id: str, session_id: str) -> None:
        """Register a new run, claiming exclusive use of its session.

        Args:
            run_id: Unique id for this run.
            session_id: Session this run will write to.

        Raises:
            SessionBusyError: If another run already owns this session.
        """
        with self._lock:
            if session_id in self._active_sessions:
                raise SessionBusyError(f"Session {session_id!r} already has an active run")
            self._active_sessions[session_id] = run_id
            self._runs[run_id] = _RunState(session_id)

    def end_run(self, run_id: str) -> None:
        """Release a run and free its session for a future run.

        Args:
            run_id: Run to release. A no-op if `run_id` is unknown (already
                ended, or never started).
        """
        with self._lock:
            state = self._runs.pop(run_id, None)
            if state is not None:
                self._active_sessions.pop(state.session_id, None)

    def push_event(self, run_id: str, event: SseEvent) -> None:
        """Enqueue an event for a run's SSE stream to pick up.

        Args:
            run_id: Run to push the event onto.
            event: Event to enqueue.

        Raises:
            UnknownRunError: If `run_id` isn't registered.
        """
        self._get_state(run_id).queue.put(event)

    def try_push_event(self, run_id: str, event: SseEvent) -> bool:
        """Enqueue an event, tolerating a reader that already disconnected.

        A run's worker thread keeps executing after its reader vanishes
        (Ctrl-C, cancellation making an abandoned run finish quickly, a
        plain dropped connection) until it hits its own next checkpoint —
        every event it tries to push in the meantime would otherwise crash
        the worker via `push_event`'s `UnknownRunError`. Callers that
        genuinely need to know about a bad run_id (tests, anything outside
        a live run's own event stream) should keep using `push_event`.

        Args:
            run_id: Run to push the event onto.
            event: Event to enqueue.

        Returns:
            `True` if enqueued, `False` if the run is no longer registered.
        """
        try:
            self.push_event(run_id, event)
        except UnknownRunError:
            return False
        return True

    def pop_event(self, run_id: str, timeout: float) -> SseEvent | None:
        """Block for the next event on a run's stream.

        Args:
            run_id: Run to read from.
            timeout: Max seconds to wait before giving up.

        Returns:
            The next event, or `None` on timeout (drives SSE heartbeats —
            not an error condition).

        Raises:
            UnknownRunError: If `run_id` isn't registered.
        """
        try:
            return self._get_state(run_id).queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def await_signal(self, run_id: str, approval_id: str, timeout: float) -> dict[str, Any] | None:
        """Block until a matching `resolve_signal` call, or timeout.

        Args:
            run_id: Run the approval belongs to.
            approval_id: Id the eventual `resolve_signal` call must match.
            timeout: Max seconds to wait.

        Returns:
            The payload passed to `resolve_signal`, or `None` on timeout.

        Raises:
            UnknownRunError: If `run_id` isn't registered.
        """
        state = self._get_state(run_id)
        signal = _PendingSignal()
        with self._lock:
            state.pending[approval_id] = signal
        fired = signal.event.wait(timeout=timeout)
        with self._lock:
            state.pending.pop(approval_id, None)
        return signal.payload if fired else None

    def resolve_signal(self, run_id: str, approval_id: str, payload: dict[str, Any]) -> None:
        """Answer a pending `await_signal` call, waking it immediately.

        Args:
            run_id: Run the approval belongs to.
            approval_id: Id matching the original `await_signal` call.
            payload: Value the waiting call receives.

        Raises:
            UnknownRunError: If `run_id` isn't registered, or no call is
                currently waiting on `approval_id` (already answered, timed
                out, or never requested).
        """
        state = self._get_state(run_id)
        with self._lock:
            signal = state.pending.get(approval_id)
        if signal is None:
            raise UnknownRunError(f"No pending signal {approval_id!r} for run {run_id!r}")
        signal.payload = payload
        signal.event.set()

    def request_cancel(self, run_id: str) -> None:
        """Signal that a run should stop gracefully at its next checkpoint.

        Args:
            run_id: Run to cancel. A no-op if `run_id` is unknown (already
                ended, or never started) — stopping an already-finished run
                isn't an error.
        """
        with self._lock:
            state = self._runs.get(run_id)
        if state is not None:
            state.cancel_event.set()

    def is_cancelled(self, run_id: str) -> bool:
        """Check whether a run has been asked to stop.

        Args:
            run_id: Run to check.

        Returns:
            `True` if `request_cancel` was called for this run. `False` for
            an unknown run_id — same "not an error" reasoning as
            `request_cancel`.
        """
        with self._lock:
            state = self._runs.get(run_id)
        return state.cancel_event.is_set() if state is not None else False

    def _get_state(self, run_id: str) -> _RunState:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise UnknownRunError(f"Unknown run: {run_id!r}")
        return state
