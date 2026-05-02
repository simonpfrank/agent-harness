# Roadmap / Todo

Durable list of things we've identified but haven't done yet. One section per item, dated when added. Add rather than edit — keep the history.

When an item ships, move it to the **Done** section at the bottom with a commit reference and the date.

---

## Near-term Improvements

### Investigate o4-mini run-1 abort (added 2026-04-15)

**What:** On the first of 5 H1p3 runs on `o4-mini` (commit `49e0799` era), the agent completed tool calls through turn 6/10 and then stopped with a `tool_result` as the last trace event — no terminal assistant message, no `write_file`, no output JSON. Subprocess exited 1 silently. Runs 2–5 on the same config succeeded (2× 11/11, 1× 10/11, 1× 9/11).

**Why:** If o4-mini is going to be a real option for this task it needs to be reliable. A ~20% silent-abort rate is not acceptable.

**Work:**
1. Capture the exact API response that led to the tool_result-as-terminal state. Might be a `length` finish reason, an empty content field, or the react loop not handling a specific stop_reason shape.
2. Check `agent_harness/loops/react.py` for how it terminates — does it require an assistant message with no tool_calls, or will it exit on other shapes?
3. Add a regression test.

---
### Harness: react loop turn/budget awareness (added 2026-04-09 approx, still open)

The react loop does not tell the model how many turns or how much budget remain. Models happily wander through 6–10 turns with no pressure to converge. A small "You have N turns / $X remaining" line injected into the system prompt at each turn would let the model self-regulate.

---

## Plausible Future Capabilities

### CLI streaming (added 2026-04-16)

**Status:** Active roadmap design

**What:** Stream model output progressively in the CLI while keeping the design reusable for a later API if one is ever built.

**Why:** This gives immediate CLI feedback on slow runs and prepares a clean event seam for any future external consumer without forcing the whole harness async.

**Scope in roadmap terms:** keep the core sync-first, start with CLI value, and avoid invasive contract changes unless they are clearly justified.

**Deep-dive design:** `docs/streaming-plan.md`

### Parallel sub-agent fan-out (added 2026-04-16)

**Status:** Active roadmap design

**What:** Run multiple delegated agents in parallel, primarily for fan-out / adjudication workflows and execution-time improvements.

**Why:** This is the most plausible parallelism win for the harness. It may improve wall-clock time and unlock useful experimentation patterns without pushing concurrency into every part of the runtime.

**Scope in roadmap terms:** sub-agent fan-out first, not parallel tool calls inside a single turn.

**Deep-dive design:** `docs/streaming-plan.md`

### API / async boundary (added 2026-04-16)

**Status:** Active roadmap design

**What:** If an external API is ever added, keep async at the boundary and avoid pre-emptively converting the harness core.

**Why:** Async is a means to an end, not a feature. The main value would be serving external consumers cleanly, not making the core more complex.

**Scope in roadmap terms:** API later, boundary-first async only, sync core by default.

**Deep-dive design:** `docs/streaming-plan.md`

### MCP support (added 2026-04-16)

Connect agents to external tools via [Model Context Protocol](https://modelcontextprotocol.io/). Scope: MCP client in the harness, config to point at MCP servers, tools auto-discovered from server capabilities.

### Evaluation framework (added 2026-04-16)

Run agents against test cases and score quality. A formal framework would add test case definitions, scoring functions, and regression detection beyond scripted CLI runs.

### Lazy tool schema loading (added 2026-04-16)

Send a compact list of tool names and descriptions first, then load full schemas on demand only when the model chooses a tool.

---

## Ideas

These are captured so they are not lost. They are not commitments.

### Identity / procedure split (added 2026-04-16)

Optional `identity.md` before `instructions.md` to separate "who the agent is" from "what it should do".

### Model fallback chains (added 2026-04-16)

If the primary provider fails, try a fallback provider before giving up. Keep it config-driven and small if it is ever built.

### Self-improving skills (added 2026-04-16)

After a successful multi-step task, the agent can save the approach as a reusable skill in `{agent_dir}/skills/` and reload it later by convention.

### Immutable trace hash chain (added 2026-04-16)

Make traces tamper-evident by including the previous event hash in each trace entry.

### Per-task cost attribution (added 2026-04-16)

Add `task_id` to trace and budget events so cost can be summed by task later.

### Decision-level approval gates (added 2026-04-16)

Explore approvals by decision severity, not just by tool, if multi-agent orchestration becomes important enough to justify it.

### Shared workspace communication (added 2026-04-16)

Use a `workspace/` directory convention for multi-agent file-based coordination instead of only fire-and-forget delegation calls.

### Agentic patterns backlog (added 2026-04-16)

Compact index entry for unshipped coordination patterns. Script-level fan-out/fan-in and consensus remain possible without framework changes; more advanced branching patterns such as Tree-of-Thoughts and LATS stay explicitly future work until there is a strong reason to pay their complexity cost.

---

## Done

### Harness: path-traversal hook false-positive (resolved 2026-04-16)

The `path_traversal_detector` now validates path-like argument names (`path`, `working_dir`, `directory`, `file_path`) against the workspace root instead of scanning every string argument for `".."`. This removes the known false-positive on free-form code/text while keeping path checks deterministic.

### OpenAI provider hardening for supported text models (resolved 2026-04-16)

The OpenAI provider now supports the selected hosted text model set (`gpt-4o`, `gpt-4o-mini`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.1`, `gpt-5-mini`, `gpt-5-nano`) through one harness-facing provider. Hosted OpenAI requests use Responses by default, OpenAI-compatible `base_url` backends keep Chat Completions for compatibility, GPT-5 cost/context metadata is present, and representative live integration tests passed on the host. `o4-mini` abort investigation remains separate.

---

## Roadmap Filter

Any new feature idea must provide a clear benefit before it belongs in this roadmap.

A feature should improve at least one of:

- user value for someone using the harness
- quality of agent outcomes
- execution time or feedback speed
- reliability, safety, or debuggability
- a concrete future capability without premature complexity

It should also pass this test:

- the benefit is greater than the added complexity
- it preserves the harness as simple, elegant, and easy to reason about

If an item cannot state a real benefit clearly, keep it in `Ideas` or do not add it.
