# API / approval interface — PRD

**Status:** Shipped 2026-08-22. See "HTTP API server" in `docs/roadmap.md`'s Done section for the as-built summary — a few things resolved differently than sketched here during the build: exclusivity is keyed on the caller's *requested* session identifier (not the resolved session's id — a real TOCTOU race the end-to-end test caught), and a run's id is returned via an `X-Run-Id` response header (not shown in the SSE stream itself, an oversight in this doc's original sketch).
**Parent roadmap items:** "Permission/approval UX for no-terminal contexts" and "API / async boundary" in `docs/roadmap.md` — this document merges both into one design, since the approval mechanism and the API transport turned out to be tightly coupled (designing one without the other would mean redesigning later once the transport shape was picked).
**Supersedes, for anything API-shaped:** `docs/streaming-plan.md`'s "API layer" section — that document predates the CLI streaming work that actually shipped and assumed FastAPI/asyncio speculatively, before any real client requirements existed. Its Part 1/2 (streaming levels, parallel-agent worker/adjudicator pattern) remain live reference for other roadmap items, just not for the API shape.

Purpose: capture the requirements and architecture decisions for adding a network API on top of the harness, sized to serve real future clients without over-building for a threat model or scale that doesn't exist yet. Mechanism-level detail (exact endpoint paths, request/response schemas, function signatures) is left to the technical spec phase, not decided here.

## Context

Checked directly before scoping, not assumed:

- Deployment is home-LAN or work-local-to-one-machine only, not internet-facing today (existing roadmap decision) — shared-secret auth + localhost-default-binding already settled as right-sized for that; full OAuth-style auth deliberately deferred.
- Concurrent runs of the same agent are now safe: isolated `tmp/<run-id>/` per run, atomic memory/session writes (shipped 2026-08-19, "Concurrency-safety for per-agent-dir state") — a real prerequisite this design depends on, now satisfied.
- `cli.py` is already a thin driver — it wires terminal I/O to `prepare_runtime`'s injected callback functions (`permission_prompt_fn`, `domain_prompt_fn`, `plan_prompt_fn`, `on_delta`, `on_thinking_delta`, etc.) and contains no harness logic itself. An API server is architecturally the same kind of thing — a second driver, not a rewrite of the core.
- None of `_permission_prompt`/`_domain_prompt`/`_plan_prompt` (`cli.py`) catch `EOFError` — a non-interactive stdin (piped input, non-interactive automation) crashes the whole process with an unhandled traceback. Hit live twice (2026-08-16). Folded into this document's scope since it's the same root cause as the broader no-terminal design here (prompts assuming a live interactive human) — see Scope.
- Real driving clients, established through discussion: a separately-built web chat UI (not part of this repo), eventually Reachy Mini (voice — its own STT/TTS, confirmed the API doesn't need voice-specific handling since the API only ever sees text either way), possibly an Echo-via-AWS-Lambda proxy "one day."

## Requirements established through discussion

1. **Streaming is required, not optional** — a slow/thinking-heavy local model (e.g. Qwen3 4B) waiting silently for a full response is a bad experience across every client type.
2. **Thinking and answer text are both deliverable, separately** — different clients want different things (a chat UI might show thinking, a voice client never should). The harness's job is to expose both, tagged; what a given client renders is not the harness's concern.
3. **Silence must be distinguishable from failure** — a client (especially voice) needs to tell "still working" apart from "the connection died." The harness can't leave that to guesswork — needs some signal even when there's no real content yet (heartbeat).
4. **Approvals must reach the client as they happen, not on a delay** — polling adds latency that lands right on top of the silence problem for voice clients, and costs real money on a per-invocation-billed deployment (Lambda) or battery on an embedded device (Reachy) if done on a timer regardless of activity. Push, not poll.
5. **Client → harness communication does not need the same urgency** — sending a message or answering an approval prompt is fine as an ordinary request; nothing requires the client to push to the harness with the same immediacy the harness needs to push to the client. This asymmetry is why a full bidirectional channel isn't needed.
6. **Interruption is required eventually, but the harness has no cancellation mechanism today** — no interrupt point anywhere in the loop code, no way to abort a running tool call or an in-flight streaming response. Detecting "the human wants to interrupt" is entirely a client concern (Escape key, a stop button, STT noticing the user talking over TTS) and differs per channel; *acting* on it once detected should be one channel-agnostic signal. Deliberately deferred (see Scope) but the transport must not foreclose adding it later.
7. **Voice clients (Reachy, Echo) are functionally equivalent to a chat UI from the API's point of view**, if STT/TTS happen entirely client-side before/after talking to the harness — if a voice app converts speech to text before sending and converts the harness's text back to speech after receiving, the API only ever sees text in both directions, same as a chat UI. Differences (thinking shown or not, silence tolerance, interruption trigger) are all client-side rendering/pacing choices layered on the same data, not different API shapes.
8. **The API addresses agents by name, not one agent per process** — an extension of the existing model (`agent_dir` is already the unit `prepare_runtime` operates on; the CLI already takes one per invocation) — a server needs requests to name which agent they mean instead of being locked to one for its process lifetime.

## Architecture decided

### Transport shape

One HTTP request per "run" (a user message → one agent turn), held open for its duration, response delivered as **Server-Sent Events (SSE)** — one-directional server→client push over that same connection. Event categories (exact schema left to spec phase):

- `delta` — answer text chunk
- `thinking_delta` — thinking text chunk. Sent unconditionally, independent of an agent's `show_thinking` config value — that setting only governs the CLI's own console display; the client decides what to do with `thinking_delta`, matching requirement 2 above ("the harness's job is to expose what's happening, not decide what a given client should render").
- `heartbeat` — no new content yet, connection and run are still alive
- `approval_needed` — the run is genuinely blocked waiting; carries enough for a client to render a prompt (tool name, arguments, a request id)
- `done` — final state (verified/not verified per `completion_check`, budget summary)
- `error`

Client → harness stays as **ordinary, separate short HTTP requests**: starting a new run, and a generic **signal endpoint** for anything that needs to reach into an in-progress run — `{"type": "approve", "decision": ...}` today, `{"type": "cancel"}` once interruption is built. Deliberately generic, not approval-specific, specifically so cancellation can be added later without redesigning this endpoint — see Scope. This also answers directly: the SSE channel is one-directional, so a cancel signal (or an approval answer) never travels over it — it always goes over this separate request path. Not a limitation to work around; it's the reason this endpoint exists.

**Rejected: full bidirectional (websockets).** The harness needs to push (streaming, approvals); the client does not need to push back with the same urgency. Websockets would buy connection-lifecycle complexity (reconnect handling — relevant for something like Reachy dropping wifi) for a client-to-server need that doesn't exist. Revisit only if a real requirement for low-latency client→server push emerges.

**Rejected: plain (non-streamed) request/response.** The harness's loop execution is an ordinary synchronous call stack today — there's no way for a request to "return and be picked back up later" without either (a) holding the original connection/thread open the whole time (which is what SSE push already is), or (b) building the loop into a genuinely resumable/serializable state machine, a much larger architectural change with no current driver.

### Concurrency model

Thread-per-request, not asyncio — reaffirms the existing 2026-08-15 roadmap decision, now grounded in a concrete reason rather than asserted: each held-open SSE connection is one thread blocked on I/O (genuinely idle, not CPU-bound), and the actual client count (chat UI, Reachy, maybe one Lambda proxy) is nowhere near the scale where thread-per-idle-connection becomes a real cost. Revisit only if a real high-fan-out driver shows up — same bar already set for the harness's own parallel-execution roadmap items.

### Auth / binding

Unchanged from the existing roadmap decision: single shared-secret header, server bound to `127.0.0.1` by default, LAN-reachability an explicit opt-in. Full auth (accounts, tokens, rotation) stays deferred until Echo/remote access is an actual plan.

**New wrinkle found during this design:** the browser's native `EventSource` API only supports GET and cannot set custom headers, so a plain browser-based chat UI using native `EventSource` cannot carry the shared-secret header this design assumes. Needs one of: the secret as a query parameter (simpler, but leaks into server logs/browser history — a real downside, not free), or the chat UI using a fetch-based SSE client instead of native `EventSource` (more client-side complexity, keeps the header approach and secrets out of logs). Not resolved here — the chat UI is a separate future build outside this repo — flagged now so it isn't discovered as a surprise later.

### Entry point / deployment

New subcommand on the existing `agent-harness` CLI — `agent-harness serve` — not a separate installable package or process type. `cli.py` is already just a driver wiring terminal I/O to `prepare_runtime`'s callbacks; a server is the same kind of driver wiring HTTP/SSE to the same callbacks instead (an approval-prompt implementation that writes into the signal-channel registry and blocks, instead of one that calls `input()`). Everything else — config loading, tool registry, loops, providers, concurrency-safety — is reused completely unchanged. One package, one install: `run` for direct local single-agent use (unchanged), `serve` to open the door for remote/multi-agent use.

This also means the API is not the only way to drive the harness core — any future client (including a fancier CLI) can either go through the network API like a remote client, or call the harness core in-process exactly like today's `cli.py` does, both built on the same underlying primitives (`prepare_runtime` + callbacks). The API doesn't become a mandatory layer everything must pass through.

### Agent addressing

The API is a layer above individual agents, not scoped to one — a run request names which agent it means (by directory/name), the same unit `prepare_runtime`/`config_loader.load` already operate on. A full agent-management surface is split into two risk tiers, not treated as one bucket:

- **List/run existing agents** — low risk, addressing something a human already reviewed and put on disk. Reasonable to build alongside the run/approval API itself.
- **Create/delete/edit agent configs remotely** — meaningfully higher risk: an agent config can grant shell/code-execution tool access, so remote config-writing is closer to "let a remote client decide what commands can run on this machine" than "let a remote client use an already-approved tool." Deliberately scoped out of this phase, to be decided with its own explicit auth thinking when there's a real driver for it.

### Session / conversation identity

Connection lifetime and conversation lifetime are deliberately not the same thing. The transport gives one connection per turn; conversation continuity across turns already has a mechanism — `session.py` — reused here, not reinvented.

**GUID-first identity, mirroring the Claude Code session model.** Today `session.py` conflates identity and label: the session *name* the caller picks is also the file's identity (`sessions/{name}.json`), so two different callers both choosing an unqualified name (e.g. "chat") collide. Splitting these: every session gets a GUID regardless of whether the caller names it, exactly like Claude Code — a name is optional and cosmetic, layered on top for human recall, never used as the identity itself. Storage moves from `sessions/{name}.json` to `sessions/{guid}.json` (or equivalent), with the optional name stored as a field, not the key. Decided now rather than left to the spec phase specifically because the session id has to appear in the run-request schema being designed right now — retrofitting this after the request shape is built would mean reshaping something already shipped, unlike most of what's in the Scope section below, which is purely additive later.

**One active connection per session id at a time — enforced, not just documented.** Two connections racing on the same session id hit a real, concrete failure mode: `save_session` writes the *entire* message list, not an append, so if both load the same starting history, append their own turn, and save, one save wins and the other caller's turn silently disappears from persisted history — even though that caller genuinely saw its own response. This isn't the same as the already-accepted "two truly concurrent writes to the same key, last-write-wins" tradeoff from the concurrency-safety work (that was about which byte layout of the *same* logical write wins); this is a whole conversational turn vanishing. Cheap to prevent — a second run request against a session already in flight is rejected (or queued), using the same in-flight-run registry the approval-signal mechanism already needs — so built now rather than left as a documented gap.

**No per-device/per-user session isolation — deliberate, documented, not an oversight.** There is no user/device identity anywhere in this design; the entire API sits behind one shared secret. Given that, "can a different device resume another device's session" isn't a session-specific question — it's the same question as "can a different caller run any agent or approve any tool call," and the answer to that is already yes for anyone holding the secret. Session access doesn't get its own protection layer on top of a trust boundary that already grants everything else. This must be stated plainly wherever the API is documented (README, `docs/features.md`) once built, not left implicit — the security question isn't "is this safe" in the abstract, it's "does the person deploying this understand exactly what the shared secret does and doesn't protect." The GUID-based identity above is what keeps this cheap to revisit: adding a real `owner` field to a session becomes additive once real auth exists, not a redesign of session identity itself, since identity was never a guessable/meaningful name to begin with.

**Documentation follow-up, to happen at build time, not now:** once this ships, `README.md` and `docs/features.md` must state the shared-secret trust model explicitly and plainly next to the session/API description — anyone deploying this needs to know a valid secret grants full access to every session and every agent, not just "the ability to chat." Flagging this now so it isn't forgotten when the feature is actually built.

## Explicitly scoped out of this phase

- **Real-time cancellation** — the harness has zero interrupt points in its loop code today (`react.py`, `rewoo.py`, etc. all run tool calls and streaming responses to completion). Building this means adding checkpoints between turns and, the hard part, actually aborting something already in flight (killing a `run_command` subprocess mid-execution, aborting a streaming provider call). Loop-level work, independent of the API transport — can be built later without reopening this design. The one constraint carried forward now: the signal endpoint above is generic, not approval-specific, so cancellation is an additive message type later, not a redesign. What happens to partial state (a half-finished answer, a half-run tool call) when a run is cut off is a real open question, deliberately deferred to when this is actually built. "Continue" vs. "redirect" after an interruption is not a second mechanism — cancellation is one primitive (stop the run); what the human says next is just the next ordinary conversational turn.
- **True suspend/resume of a run** — rejected outright above, not deferred; no evidence it's needed given the held-open-connection model covers the actual requirement.
- **Full auth (accounts, tokens/rotation, OAuth)** — deferred per the existing roadmap decision, unchanged by this document.
- **Agent create/delete/edit via the API** — deferred per Agent addressing above.
- **Websockets** — rejected, not deferred; revisit only if a genuine low-latency client→server push need emerges.
- **Reconnect gap-recovery** — if a client's connection drops mid-run (e.g. Reachy losing wifi), reconnecting does not currently recover missed events; the client would need to separately ask "what's the current state of run X" as a fallback, which isn't designed here either. Accepted gap for this phase, consistent with not building true suspend/resume.

## Open questions carried into the technical spec (not decided here)

- Exact event/message schemas (field names, run-id format).
- Exact endpoint paths and HTTP methods.
- Signal-channel registry implementation (in-memory dict + `threading.Event`, keyed by run id, is the shape discussed — not yet the spec).
- Heartbeat interval.
- What happens to a run whose SSE connection drops without the client ever reconnecting — does the harness keep running to completion in the background, or is there a cap.
