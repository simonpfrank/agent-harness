# Real cancellation ("stop") — PRD

**Status:** Shipped 2026-08-23. See `docs/roadmap.md`'s "Real cancellation" Done entry for the build summary and real, zero-mock verification (including a genuine reader-disconnect race found and fixed live, not scoped here originally).

## Origin

Deferred deliberately during the HTTP API server build and again during the
live-dogfooding session that followed it (see `docs/roadmap.md`'s "HTTP API
server" entry, "Explicitly scoped out" note, and its third same-day
addendum). At the time: client crashes were the more urgent problem
(addressed via disconnect-triggered session-lock release, testable via
Ctrl-C on `chat/cli.py`), and the user's own stated sequencing was to get a
working Streamlit app in daily use first, then build real stop once they
actually wanted it. That point has now arrived, prompted concretely by
local-model runs where the model rambles in its thinking for a long time on
a trivial question and there's no way to make it stop early short of
killing the whole client.

## What's actually interruptible — grounded in the real code, not assumed

- **Turn boundary** (before the next LLM call starts) — trivial. `ralph.py`
  already has the exact precedent: `if cb.is_budget_exceeded and
  cb.is_budget_exceeded(): ...` checked before starting a fresh attempt.
  `is_cancelled` follows the identical shape.
- **Mid-stream** (a streaming LLM call) — buildable, not free. `anthropic.py::_stream_deltas`
  consumes a plain `for event in stream:` loop inside a `with
  client.messages.stream(...) as message_stream:` block
  (`anthropic.py:219`); breaking out early and closing the context manager
  stops reading, but `stream.get_final_message()` (called right after the
  loop today) needs verifying empirically — does it return the partial
  accumulated message cleanly on an early exit, block, or raise? Not
  assumed; must be confirmed against the real SDK during build, same
  discipline as the earlier `reasoning_content` investigation.
- **Mid non-streaming LLM call** — **not** abortable. One blocking HTTP call
  under the hood in both SDKs; a stop signal can't interrupt it mid-flight,
  only decide not to act on the result once it lands (no better than the
  turn-boundary checkpoint, and the tokens are already spent either way).
- **Mid tool execution** — **not** abortable today. `run_command`/`execute_code`
  use blocking `subprocess.run`, not `Popen`; no live handle to kill early.
  **Explicitly out of scope for this build** (confirmed with the user) —
  restructuring `tools.py` to `Popen`+poll is real, separate work with no
  evidence it's the actual pain point (the driving case is rambling
  *thinking*, which happens before any tool call, not a stuck tool). A stop
  requested while a tool call (or a parallel batch of them) is in flight
  takes effect only once that call/batch finishes on its own — the loop
  then sees the flag before starting the next turn and stops there instead.
  **Confirmed acceptable to the user as v1 scope**, with the gap stated
  plainly rather than glossed over.

## Confirmed scope (via direct discussion + AskUserQuestion)

1. **Interrupt points:** turn boundary + mid-stream only. No tool-call
   killing in this build.
2. **Applies to both the API and the plain CLI.** The plain `agent-harness
   run`/REPL gets a graceful Ctrl-C (SIGINT) stop using the same checkpoints,
   not just a hard process kill — cheap, since the checkpoints are shared
   code.
3. **`chat/cli.py`'s Ctrl-C sends a real cancel signal**, not just
   disconnecting. Completes the earlier disconnect-lock-release work: today
   Ctrl-C releases the session lock immediately but the abandoned run keeps
   executing server-side until it finishes on its own; this build makes
   Ctrl-C also tell the server to actually stop.
4. **Streamlit's Stop button is explicitly deferred, not bundled here.**
   `chat/app.py` blocks the whole script on `st.write_stream` while
   streaming — Streamlit can't process a button click until that call
   returns, so a naive Stop button can't be clicked mid-stream with the
   current structure. Making it clickable needs restructuring `chat/app.py`
   (background thread + polling, roughly) — a separate follow-up once the
   underlying mechanism exists and is proven via `chat/cli.py`.

## Mechanism sketch (to be firmed up in plan mode, not final)

- `types.py::LoopCallbacks` gains `is_cancelled: Callable[[], bool] | None`,
  same shape as the existing `is_budget_exceeded`.
- `react.py`: checked at the top of the turn loop (same spot `ralph.py`
  checks budget) — stop and return whatever's accumulated so far, same
  "graceful stop, not a crash" behavior as hitting `max_turns`/budget today.
- Streaming providers (`anthropic.py`, `openai_provider.py`'s Chat
  Completions and Responses paths): a cancellation check threaded into the
  delta-consuming loop, checked per-chunk — same wiring pattern as
  `on_delta`/`on_thinking_delta` (an additional kwarg through `chat_fn`).
- `api/registry.py::RunRegistry`: a per-run `threading.Event` for
  cancellation, parallel to the existing per-approval `_PendingSignal.event`
  — `request_cancel(run_id)` / `is_cancelled(run_id)`.
- `api/routes.py`: the already-generic `POST /runs/<run_id>/signal` endpoint
  gets a real `{"type": "cancel"}` body (the shape was reserved but
  unimplemented since the API's original build).
- `cli.py`: a `signal.signal(signal.SIGINT, ...)` handler installed for the
  duration of a run, setting a local `threading.Event` read by the same
  `is_cancelled` callback — CLI needs no registry, it's single-process.
- `chat/cli.py`: catch the existing Ctrl-C path, `POST` a cancel signal to
  `/runs/<run_id>/signal` before tearing down the local connection.

## Explicitly deferred (unchanged from the original API PRD)

True suspend/resume of a run (different from stop — nothing here allows
resuming a stopped run from where it left off). Mid-tool-call kill (see
above). Streamlit's actual Stop button UX (see above).
