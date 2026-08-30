"""Flask app: HTTP/SSE driver wiring requests to the harness core.

Architecturally a sibling of `cli.py` — both are thin drivers that supply
their own callback implementations to `prepare_runtime`; this one uses
HTTP/SSE instead of terminal I/O.
"""

from __future__ import annotations

import logging
import secrets
import threading
import uuid
from collections.abc import Generator
from typing import Any

from flask import Flask, Response, jsonify, request

from agent_harness import config as config_loader
from agent_harness.api.callbacks import (
    CompletionStatus,
    SeqCounter,
    build_output_sink,
    make_domain_prompt,
    make_permission_prompt,
    make_plan_prompt,
)
from agent_harness.api.events import CANCELLED, DONE, ERROR, SseEvent, format_sse
from agent_harness.api.registry import RunRegistry, SessionBusyError, UnknownRunError
from agent_harness.log import setup_logging
from agent_harness.runtime import prepare_runtime
from agent_harness.session import Session, load_session_by_id, resolve_or_create_session, save_session, session_path
from agent_harness.types import AgentConfig

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 15.0


def create_app(agents_dir: str = "agents", api_key: str | None = None, registry: RunRegistry | None = None) -> Flask:
    """Build the API's Flask app.

    Args:
        agents_dir: Directory containing one subfolder per agent.
        api_key: Shared secret required on every request via the
            `X-API-Key` header. `None` disables auth entirely (only
            appropriate for local testing, never a real deployment).
        registry: Run registry to use. Defaults to a fresh one — overridable
            for tests that need to pre-seed or inspect run state.

    Returns:
        Configured Flask app, not yet running.
    """
    app = Flask(__name__)
    if registry is None:
        registry = RunRegistry()

    @app.before_request
    def _check_auth() -> tuple[Response, int] | None:
        if api_key is None:
            return None
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, api_key):
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.get("/agents")
    def list_agents() -> Response:
        return jsonify({"agents": config_loader.list_agent_names(agents_dir)})

    @app.post("/agents/<name>/runs")
    def start_run(name: str) -> tuple[Response, int] | Response:
        return _handle_start_run(registry, agents_dir, name, request.get_json(silent=True) or {})

    @app.post("/runs/<run_id>/signal")
    def signal(run_id: str) -> tuple[Response, int]:
        return _handle_signal(registry, run_id, request.get_json(silent=True) or {})

    return app


def _resolve_session(sessions_dir: str, body: dict[str, Any]) -> Session | None:
    """Resolve the session a run request refers to, or `None` for a
    stateless one-shot run (no `session_id`/`session_name` given)."""
    session_id = body.get("session_id")
    if session_id:
        session = load_session_by_id(sessions_dir, session_id)
        if session is None:
            session = Session(id=session_id, name=body.get("session_name"), messages=[])
        return session
    session_name = body.get("session_name")
    if session_name:
        return resolve_or_create_session(sessions_dir, session_name)
    return None


def _handle_start_run(
    registry: RunRegistry, agents_dir: str, name: str, body: dict[str, Any],
) -> tuple[Response, int] | Response:
    message = body.get("message")
    if not message:
        return jsonify({"error": "'message' is required"}), 400
    try:
        config = config_loader.load(f"{agents_dir}/{name}")
    except FileNotFoundError:
        return jsonify({"error": f"Unknown agent: {name!r}"}), 404
    except Exception as exc:  # noqa: BLE001 - malformed config.yaml/instructions.md; report it, don't 500 raw
        logger.exception("Failed to load agent %r", name)
        return jsonify({"error": f"Could not load agent {name!r}: {exc}"}), 400

    sessions_dir = f"{config.agent_dir}/sessions"
    run_id = uuid.uuid4().hex
    # Exclusivity is claimed on the caller's *requested* identifier, before
    # any session file lookup — resolving-by-name is a find-or-create that
    # isn't itself atomic, so keying on the resolved session's id would let
    # two concurrent first-time requests for the same name both find
    # nothing on disk and each create a distinct id, never colliding here.
    exclusivity_key = body.get("session_id") or body.get("session_name") or run_id
    try:
        registry.start_run(run_id, exclusivity_key)
    except SessionBusyError:
        return jsonify({"error": "Session already has an active run"}), 409

    session = _resolve_session(sessions_dir, body)
    worker = threading.Thread(
        target=_run_worker, args=(registry, run_id, config, sessions_dir, session, message), daemon=True,
    )
    worker.start()
    resp = Response(_sse_stream(registry, run_id), mimetype="text/event-stream")
    resp.headers["X-Run-Id"] = run_id  # the only way a client learns this run's id, needed to answer approvals
    return resp


def _run_worker(
    registry: RunRegistry, run_id: str, config: AgentConfig, sessions_dir: str, session: Session | None, message: str,
) -> None:
    """Thin safety net around `_execute_run`, and sole guarantor that a run
    always releases its session lock.

    `_sse_stream` *also* calls `registry.end_run` when it sees a `done`/
    `error` event — but that only fires if a reader is still consuming the
    stream. This worker runs independently of whether anyone is: if the
    client vanishes (closed, network dropped, machine slept) before
    consuming the terminal event, the worker still finishes its job, but
    nothing else is left to release the lock. Confirmed live: a session
    stayed marked busy long after the reading client was gone, with no
    relationship to any timeout. `end_run` is idempotent (a no-op if
    already released), so calling it here unconditionally is always safe,
    whether or not `_sse_stream` also calls it.
    """
    seq = SeqCounter()
    try:
        _execute_run(registry, run_id, config, sessions_dir, session, message, seq)
    except Exception as exc:  # noqa: BLE001 - last-resort: must never leave a run silently hung
        logger.exception("Run %s crashed unexpectedly", run_id)
        # The run may have already ended (a terminal event was pushed and
        # the reader already released it) before this crashed — nothing
        # left to tell, and nothing left to clean up.
        registry.try_push_event(run_id, SseEvent(ERROR, {"message": f"Internal error: {exc}"}, seq.next()))
    finally:
        registry.end_run(run_id)


def _execute_run(
    registry: RunRegistry,
    run_id: str,
    config: AgentConfig,
    sessions_dir: str,
    session: Session | None,
    message: str,
    seq: SeqCounter,
) -> None:
    completion_status = CompletionStatus()
    output_sink = build_output_sink(registry, run_id, seq, completion_status)
    runtime = prepare_runtime(
        config,
        permission_prompt_fn=make_permission_prompt(registry, run_id, seq),
        domain_prompt_fn=make_domain_prompt(registry, run_id, seq),
        plan_prompt_fn=make_plan_prompt(registry, run_id, seq),
        show_output=False,
        trace_enabled=True,
        output_sink=output_sink,
        is_cancelled_fn=lambda: registry.is_cancelled(run_id),
    )
    messages = runtime.init_messages(session=session)
    final_text: str | None = None
    errored = False
    try:
        final_text = runtime.run_messages(messages, prompt=message)
    except RuntimeError as exc:
        logger.warning("Run %s failed during execution: %s", run_id, exc)
        registry.try_push_event(run_id, SseEvent(ERROR, {"message": str(exc)}, seq.next()))
        errored = True
    if session is not None:
        session.messages = messages
        save_session(session, session_path(sessions_dir, session))
    runtime.finalize()
    if errored:
        # The `error` event above already ended the run for the reader
        # (`_sse_stream` releases the session lock on the first terminal
        # event it sees) — pushing a second terminal event here would hit
        # an already-unregistered run and crash the worker thread instead
        # of ending cleanly. Real bug, found live: an LM Studio model
        # reload failure triggered exactly this.
        return
    terminal_event = CANCELLED if registry.is_cancelled(run_id) else DONE
    registry.try_push_event(run_id, SseEvent(terminal_event, {
        "verified": completion_status.verified,
        "detail": completion_status.detail,
        "budget_summary": runtime.budget.summary(),
        "final_text": final_text,
        "session_id": session.id if session is not None else None,
        "session_name": session.name if session is not None else None,
    }, seq.next()))


def _sse_stream(registry: RunRegistry, run_id: str) -> Generator[str, None, None]:
    # `finally` wraps the whole body (including the very first yield) so
    # the session lock is released on *every* exit path: a terminal event
    # arriving normally, or the client disconnecting at any point at all
    # (Ctrl-C, closed terminal, dropped network) — Python tears a generator
    # down via GeneratorExit the moment its consumer stops iterating it,
    # and without this, nothing released the lock until the abandoned run
    # eventually finished on its own (the worker's own `finally: end_run`
    # is still the backstop for a client that vanishes before ever
    # starting to read at all). `end_run` is idempotent, so it's always
    # safe to call here regardless of which path got there first.
    try:
        heartbeat_seq = 0
        yield format_sse(SseEvent("heartbeat", {}, heartbeat_seq))
        heartbeat_seq -= 1
        while True:
            event = registry.pop_event(run_id, timeout=HEARTBEAT_INTERVAL_SECONDS)
            if event is None:
                yield format_sse(SseEvent("heartbeat", {}, heartbeat_seq))
                heartbeat_seq -= 1
                continue
            yield format_sse(event)
            if event.event in (DONE, CANCELLED, ERROR):
                return
    finally:
        registry.end_run(run_id)


def _handle_signal(registry: RunRegistry, run_id: str, body: dict[str, Any]) -> tuple[Response, int]:
    if body.get("type") == "cancel":
        # No-op on an unknown/already-finished run — the caller's intent
        # (this run should stop) is trivially already satisfied, not an error.
        registry.request_cancel(run_id)
        return jsonify({"status": "ok"}), 202

    approval_id = body.get("approval_id")
    decision = body.get("decision")
    if not approval_id or not decision:
        return jsonify({"error": "'approval_id' and 'decision' are required"}), 400
    try:
        registry.resolve_signal(run_id, approval_id, {"decision": decision})
    except UnknownRunError:
        return jsonify({"error": "No matching pending approval for this run"}), 404
    return jsonify({"status": "ok"}), 202


def serve(
    host: str = "127.0.0.1",
    port: int = 8420,
    agents_dir: str = "agents",
    api_key: str | None = None,
    verbose: bool = False,
) -> None:
    """Run the API server.

    Args:
        host: Bind address. Defaults to localhost only.
        port: Port to listen on.
        agents_dir: Directory containing one subfolder per agent.
        api_key: Shared secret required on every request, or `None` to
            disable auth (local testing only).
        verbose: If True, set console log level to DEBUG (default INFO).
            Console-only — `serve` isn't scoped to one agent_dir, so there's
            no single place for the per-agent file logging `run` uses.
    """
    setup_logging(agent_dir=None, verbose=verbose)
    if api_key is None:
        logger.warning("Starting API server with no api_key configured — every request is unauthenticated")
    create_app(agents_dir=agents_dir, api_key=api_key).run(host=host, port=port, threaded=True)
