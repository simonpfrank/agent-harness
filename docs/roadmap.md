# Roadmap / Todo

Durable list of things we've identified but haven't done yet. One section per item, dated when added. Add rather than edit — keep the history.

When an item ships, move it to the **Done** section at the bottom with a commit reference and the date.

---

## Open

### OpenAI GPT-5.x models — test and adjust provider (added 2026-04-15)

**What:** Support OpenAI's current flagship family (`gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` — whatever the current names are at the time of implementation) in the agent harness, and test them on the column-matching experiment.

**Why:** Round 1 of the column-matching experiment (see `docs/matcher_experiments.md`) compared Haiku 4.5 vs gpt-4o vs gpt-4o-mini. Haiku hit 11/11 deterministically; the gpt-4o family flatlined at 5/11. That may be a gpt-4o-specific limitation. The 5.x family is the modern OpenAI equivalent of Haiku's tier and is the fair comparison.

**Known gaps:**
- `agent_harness/budget.py` COST_TABLE has no entries for any gpt-5 model — cost would log as $0.
- `agent_harness/providers/openai_provider.py` has no model-specific branching; unclear if 5.x accepts the same kwargs we send today (`temperature`, `max_tokens`, `top_p`). Some current-gen models require `max_completion_tokens` instead of `max_tokens`.

**Work:**
1. Confirm current model IDs and pricing from OpenAI's pricing page.
2. Add cost-table entries.
3. If the API rejects our kwargs, extend the provider's kwarg allowlist per-model (see the reasoning-model item below for a parallel pattern).
4. Run H1p3 config from the matcher experiments on the 5.x-mini or -nano tier. Compare to Haiku 4.5.

**Definition of done:** 5 runs on a 5.x model logged in `docs/matcher_experiments.md` results table with real cost and accuracy, plus a paragraph in Findings answering "did 5.x close the gap or not".

### OpenAI reasoning models (o1/o3/o4) — provider support (added 2026-04-15)

**What:** Support OpenAI's reasoning models in the harness.

**Why:** Open question from the matcher experiment: is reasoning the lever, or is it vendor instruction-following style? gpt-4o flatlined at 5/11; Haiku hit 11/11. Running the same prompt on `o4-mini` (or similar) would tell us whether a reasoning-style model bridges the gap or whether the vendor-level tool-literal pattern persists regardless of reasoning.

**Known gaps:**
- Reasoning models reject `temperature` and `top_p` — current provider always forwards them if set.
- They use `max_completion_tokens` instead of `max_tokens`.
- They accept `reasoning_effort: low|medium|high`, which we have no plumbing for.
- No cost-table entries.

**Work:**
1. Detect model by prefix (`o1`, `o3`, `o4`) in `openai_provider.py`.
2. For reasoning models, drop `temperature`/`top_p` from `create_kwargs`, rename `max_tokens` → `max_completion_tokens`, and optionally accept a `reasoning_effort` kwarg.
3. Unit test: passing `temperature` to a reasoning model must silently drop it, not error.
4. Cost-table entries for the picked models.
5. Run H1p3 on the chosen reasoning model; update `docs/matcher_experiments.md` Findings with the reasoning-vs-vendor-style answer.

**Definition of done:** A small integration test hitting a real reasoning model succeeds; one reasoning-model row appended to the matcher experiment results table with interpretation.

### Harness: path-traversal hook false-positive (added 2026-04-09 approx, still open)

The `path_traversal_detector` hook inspects all tool-argument string values for `".."` and blocks the call. It fired on an `execute_code` run during one of the earlier column-matcher reflection experiments because the agent-generated Python string contained `..` (e.g. `"Birth..confirmation"`). The tight prompt currently avoids `execute_code`, so this hasn't recurred — but the hook's current shape can false-positive on any tool that takes free-form text.

**Fix direction:** scope the check to arguments that are documented as paths (name-based allowlist from the tool's schema), not "every string anywhere in the call".

### Harness: react loop turn/budget awareness (added 2026-04-09 approx, still open)

The react loop does not tell the model how many turns or how much budget remain. Models happily wander through 6–10 turns with no pressure to converge. A small "You have N turns / $X remaining" line injected into the system prompt at each turn would let the model self-regulate.

---

## Done

(empty — move items here with commit ref + date when they ship)
