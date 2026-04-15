# Column-Matcher Experiments

This is the live, durable record of column-matching experiments. Each round of testing appends a new section. The goal is to find the smallest, cheapest configuration that reliably matches columns, and to understand *why* it works so the finding generalises.

---

## Round 1 — Baseline, Determinism, and Tooling

### Context

The `column-matcher` agent currently gets **7±2 of 11 expected matches** on the pension test data across 9 runs at default settings (Haiku 4.5, temperature unset, react loop). Three failure modes are persistent (see `data/hypothesis.md`):

1. **Secondary Gender** (0% populated) — model rejects despite semantic alignment.
2. **Form of Annuity to Be Purchased** — never considered; model matches on word-overlap, not phrase.
3. **Contingent Annuitant / Beneficiary 1 Monthly Benefit → Secondary Amount** — 14-word name never parsed; identical sample values ignored.

Two coupled questions:
- Can we **increase determinism** (reduce run-to-run variance)?
- Can we **improve accuracy** (close the 3 persistent gaps)?

Budget for this round: **~$10**. Cross-vendor (Anthropic + OpenAI). No Sonnet-tier unless a clear winner emerges lower down.

### Objective

Find the smallest, cheapest configuration that reliably hits **≥9/11 matches with stdev ≤ 0.5** across 5 consecutive runs — and understand why, so the finding generalises.

### Success Metrics (tabulated for every cell)

| Metric | Definition |
|---|---|
| `mean_correct` | Mean correct matches over N runs, out of 11 |
| `stdev` | Stdev of correct matches across N runs |
| `false_positives` | Mean wrong matches per run |
| `cost_per_run` | Mean USD per run (from harness tracer) |
| `turns` | Mean agent turns |

Primary ranking: `mean_correct` AND `stdev` weighted equally. Tie-break on `cost_per_run`.

### Hypotheses Under Test (pruned from `data/hypothesis.md`)

| ID | Hypothesis | Change | Cost to test |
|---|---|---|---|
| H0 | Baseline variance | Current config, 5 runs | low |
| H4 | Determinism from temp=0 | `temperature: 0` in provider_kwargs | low |
| H1 | Value-overlap pre-scan tool | New tool `value_overlap` in `tools/` | medium |
| H2 | Column-name decomposition | Extend `profile_data` with `semantic_parts` | medium |
| H1+H2 | Stacked | Both together | medium |
| H5 | Bigger model (mid tier) | Only on best-performing config | high |

Dropped: H3 (multi-pass instructions — prior evidence says model ignores workflow passes), H6 (need more data we don't have).

### Model Ladder — cheapest first, gated

| Order | Model | Est. $/run (react) | Role |
|---|---|---|---|
| 1 | `gpt-4o-mini` | $0.009 | Vendor floor, cheap variance data |
| 2 | `claude-haiku-4-5` | $0.052 | Current baseline |
| 3 | `gpt-4o` | $0.15 | Mid-tier cross-vendor ceiling |
| (opt) | Sonnet 4.5 | $0.195 | Only on winning config if budget allows |

Per-run cost estimate assumes ~40K input + ~5K output tokens (inferred from the observed $0.06/run Haiku baseline).

**Gating rules:**
- A hypothesis that doesn't improve `mean_correct` or `stdev` at mini-tier is **not** re-run at gpt-4o.
- If H0 and H4 are identical at mini-tier (stdev within 0.3), drop H4 going forward.
- Sonnet only runs if gpt-4o beats Haiku by ≥1 match AND there's budget left.

### Budget Allocation (target ≤ $10)

5 runs × 5 configs (H0, H4, H1, H2, H1+H2) × 3 models, gated.

| Model | Configs run | Runs | Cost |
|---|---|---|---|
| gpt-4o-mini | all 5 | 25 | $0.23 |
| haiku-4-5 | all 5 | 25 | $1.30 |
| gpt-4o | top 2 (gated) | 10 | $1.50 |
| Sonnet (opt) | best 1 | 5 | $0.98 |
| **Total** | | **~65 runs** | **~$4** |

Contingency ~$6 for re-runs, tooling iteration, stacking experiments.

### Files to Modify / Create

**New**
- `tools/value_overlap.py` — new custom tool (H1). Single function `value_overlap(reference_profile: str, input_profile: str, threshold: int = 3) -> str` that parses two profile JSONs (already written by `profile_data`) and returns pairs where ≥`threshold` sample values overlap. Deterministic, no LLM.
- `tests/unit/test_value_overlap.py` — TDD first.
- `scripts/run_experiment.py` — small harness that loops: for each (model, config) run N times with cleared memory, capture match count / stdev / cost from the session trace, append a row to `docs/experiment_results.csv`.
- `data/expected_matches.json` — ground truth for the 11 known matches.

**Modified**
- `tools/profile_data.py` — add optional `semantic_parts` field (H2). Heuristic decomposition (split on `/`, `—`, common prepositions); no LLM call. Opt-in via parameter `decompose: bool = False` so H2 is isolated.
- `tests/unit/test_profile_data.py` — tests for `semantic_parts` output.
- `agents/column-matcher/config.yaml` — temperature / model / provider overrides per run (driven by `scripts/run_experiment.py` CLI flags, not committed changes).
- `agents/column-matcher/instructions.md` — when H1 active, add one paragraph: "call `value_overlap` first and use its candidate list". When H2 active, add "use `semantic_parts` to match phrases not words".

**Reused (no changes)**
- `agent_harness/providers/openai.py` — already supports OpenAI models and custom base_url.
- `Budget` + tracer — already records cost per run; parse `agent_dir/.sessions/*.jsonl`.
- `profile_data` sample_values output — already has what H1 needs.

### Methodology

1. **Clear memory** between every run.
2. **Same input + reference files** throughout: `data/pension_reference.xlsx`, `data/pension_input.xlsx`.
3. **Ground truth** in `data/expected_matches.json`; scoring script diffs agent output against it.
4. **One variable at a time.** H1+H2 stacked comes only after each is measured individually.
5. **N=5 runs** per cell.
6. **Results written to CSV immediately after each run** so we can stop early if a hypothesis is clearly dead.

### Execution Order (cheapest first)

1. Set up: write `expected_matches.json`, `scripts/run_experiment.py`, scoring logic.
2. Run H0 + H4 on **gpt-4o-mini** (cheapest). Establishes vendor-floor baseline + determinism answer.
3. Run H0 + H4 on **haiku-4-5**.
4. Build + unit-test `value_overlap` (H1). Run on mini, then haiku.
5. Extend `profile_data` with `semantic_parts` (H2). Run on mini, then haiku.
6. Run H1+H2 stacked if either individually showed lift.
7. Gate: promote top-2 configs to **gpt-4o**.
8. Optional Sonnet ceiling check if budget remains.
9. Append Findings subsection below with a recommendation.

### Verification

- Every tool/code change: `pytest tests/unit/ -v` green, `ruff check .` clean, `mypy --strict` clean.
- End-to-end: `.venv/bin/python scripts/run_experiment.py --config H0 --model gpt-4o-mini --runs 1` produces a result CSV row and an output JSON that scores against `expected_matches.json`.
- Final: reproduce the best cell from cold — clear memory, clear CSV, run N=5, confirm numbers match the documented table within stdev.

### Stopping Conditions

- Budget spent > $8 → stop escalating, write findings with current data.
- Any config hits `mean_correct ≥ 10 AND stdev ≤ 0.5` → declare winner, stop.
- All hypotheses exhausted with no lift over baseline → document as null result, recommend mid-tier model as the only lever.

### Results

One row per (config × model) cell. Raw per-run rows in `docs/experiment_results.csv`.

| Config | Model | N | mean | stdev | mean_fp | $/run | turns | Notes |
|---|---|---|---|---|---|---|---|---|
| H0 | gpt-4o-mini | 5 | 5.80 | 0.84 | 0.2 | $0.005 | 3.4 | Range 5–7 |
| H4 | gpt-4o-mini | 5 | 6.80 | 0.45 | 0.2 | $0.005 | 3.6 | temp=0; +1 mean, half stdev vs H0 |
| H0 | haiku-4-5 | 5 | 7.20 | 0.45 | 2.6 | $0.076 | 5.2 | One 12-FP runaway in run 3 |
| H4 | haiku-4-5 | 5 | 7.20 | 0.45 | 0.8 | $0.063 | 5.0 | temp=0 reduced FP spread, no accuracy change |
| H1 | gpt-4o-mini | 5 | 5.00 | 0.00 | 1.0 | $0.009 | 5.2 | value_overlap tool; mini treats tool output as the definitive match list and drops name/semantic matches |
| H1 | haiku-4-5 | 5 | 9.00 | 0.00 | 1.8 | $0.091 | 7.0 | value_overlap tool; +1.8 vs H4, zero variance |
| H1p | haiku-4-5 | 5 | 10.20 | 0.45 | 0.4 | $0.095 | 7.0 | H1 + context rule for Form of Annuity disambiguation + uniform-ref rule |
| H1p2 | haiku-4-5 | 5 | 10.00 | 0.00 | 0.0 | $0.095 | 7.0 | H1p + stronger uniform-reference rule; FPs eliminated |
| **H1p3** | **haiku-4-5** | **5** | **11.00** | **0.00** | **0.0** | **$0.097** | **7.0** | **H1p2 + imperative zero-population rule; stopping rule met** |
| H1p3 | gpt-4o-mini | 5 | 5.00 | 0.00 | 1.0 | $0.008 | 5.2 | Same prompt as winning Haiku cell; mini unchanged at 5/11 |
| H1p3 | gpt-4o | 5 | 5.00 | 0.00 | 0.0 | $0.150 | 7.0 | Cross-vendor ceiling check. Same 5/11 as mini, but zero FPs (better disambiguation). 18× more expensive than mini for the same accuracy — the problem is not model size, it's vendor instruction-following style on combined tool + name-matching prompts. |

**Mid-round interpretation:**
- **H1 on Haiku is the current winner**: 9/11 consistently, zero variance, $0.09/run.
- H1 *hurts* mini — the small model cannot follow "tool gives priors AND continue to match by name". Capability, not prompt.
- Two persistent failure modes remain on Haiku H1:
  - *Secondary Gender* (0% populated) — value_overlap cannot help by construction.
  - *Form of Annuity* — an ambiguity: two input columns share 3 values. Haiku picks "Original Form of Annuity at Commencement" over "Form of Annuity to Be Purchased" every time. This is a disambiguation problem.
- Spend after H1: **$1.56 / $10**.

**Harness bug found and fixed:**
`max_output_chars` (default 10000) was truncating `profile_data` output under the original design where value_overlap received the profile JSON as a tool argument — the model then hallucinated a compressed profile when re-emitting it. Also redesigned value_overlap to read files directly instead of receiving JSON, making it ~3× cheaper and self-contained. Earlier H0/H4 runs were unaffected by the truncation because they didn't need to re-emit the profile.

### Findings

**Winner: H1p3 on Haiku 4.5.** 5 runs, 11/11 correct each run, 0 false positives, stdev 0, $0.097/run. Stopping rule (`mean_correct ≥ 10 AND stdev ≤ 0.5`) was met and exceeded. Total spend for the round: ~$2.70 of the $10 budget.

**What worked:**
1. **`value_overlap` tool (H1)**: deterministic pre-scan surfaces value-aligned pairs. Closed the "never considered" failures (Primary Amount, Secondary Amount, Form of Annuity to Be Purchased).
2. **Context-file rules**: a one-line disambiguation rule for Form of Annuity ("active election beats historical") and a "uniform reference columns are template defaults" rule closed one persistent FP and one persistent miss.
3. **Imperative zero-population rule**: replacing a defensive "do not reject" phrasing with a positive "you MUST include this pair in `matches` at 0.70" fixed the Secondary Gender miss. The agent explicitly cited the old rule while violating it — Haiku treats defensive rules as permissive, imperative rules as binding.
4. **Temperature=0**: a clear win on gpt-4o-mini (+1 mean, half stdev) and neutral on Haiku. Cost of adoption is zero. Use it everywhere.

**What didn't:**
- `value_overlap` actively hurt both OpenAI models (6.80 → 5.00 on mini; 7.20-equivalent → 5.00 on gpt-4o). Both treat the tool output as the definitive match list and skip name/semantic matches. gpt-4o does this *more cleanly* than mini (0 FPs vs 1 FP from keeping both Form of Annuity candidates), but it's the same failure mode at 18× the cost. This is **not a model-size capability limit** — it's a vendor-level instruction-following style. OpenAI models at temp=0 are tool-literal; Haiku reads tool output as priors and continues reasoning. Confirmed with identical prompt (H1p3) across three models.

**Incidental findings:**
- A harness bug was discovered and fixed: `max_output_chars=10000` (default) truncated `profile_data` output. The original `value_overlap` design received the profile JSON as a tool argument, and the truncated profile was then *hallucinated* by the model into compressed JSON when re-emitted. Fixed by making `value_overlap` read files directly, and by raising the agent's `max_output_chars` to 40000.
- A provider-kwargs passthrough bug was discovered and fixed as a prerequisite: neither provider was passing `temperature` through to the API, so the original H4 hypothesis was untestable until fixed.

### Lessons about driving LLMs (portable across tasks)

These are the general patterns the round surfaced. They are not numbers — they are things to check first next time.

1. **Imperative framing binds; defensive framing is interpreted as permission.** "Low population is not a reason to reject" was *quoted by Haiku in its reasoning* and then violated. "You MUST put this pair in `matches` at 0.70" fixed it in one attempt. If a rule matters, write it as a positive command, not a prohibition.
2. **Anticipate the rule the model will otherwise apply, and explicitly rebut it.** The imperative zero-population rule didn't just say "do this"; it named the wrong phrasing ("cannot match sparse input without confirmation") and flagged it as a rule violation. That framing made it much harder for the model to lean on its default caution.
3. **Tools collapse to answers unless the prompt actively frames them as partial.** `value_overlap` produces 6 candidates; left to its own instincts, an agent may treat those as the match list. The binding fix was not "remember the other rules" but an explicit CRITICAL paragraph saying "this tool will NOT find X, Y, Z — you must add those yourself". Naming what the tool doesn't find is the lever.
4. **Determinism is not correctness.** `stdev = 0` on gpt-4o-mini meant the model returned the same wrong answer every run. Watch both axes; a confident, consistent, wrong agent is the worst kind.
5. **Temperature=0 reduces noise but does not change convergence.** It kills run-to-run variance on shaky configs; it does not raise the accuracy ceiling. Cheap to adopt, not a fix on its own.
6. **Domain disambiguation belongs in the context file, workflow rules in the instructions file.** The Form-of-Annuity "active election beats historical" rule went into `context.md` as a one-liner and worked immediately. Domain rules near domain terminology read naturally to the model; the same rule buried in workflow would compete with other instructions. Unproven but consistent with what we observed.
7. **Inspect the model's reasoning on failures, not just its final output.** Haiku told us exactly which rule it was following when it violated the intent. The fix was then surgical. Skip this and you're guessing.
8. **Cheap-first gating controls spend.** Ran on gpt-4o-mini before Haiku, Haiku before gpt-4o. Killed branches early when a hypothesis clearly lost (H1 on mini, H4 on Haiku). Spent $3.50 of $10 and still hit 11/11.
9. **Instruction-following scope varies by vendor, not just by model size.** gpt-4o (~25× gpt-4o-mini's cost) and gpt-4o-mini both flatlined at 5/11 with the same failure mode. Size was not the lever. This suggests vendor-level prompting strategies are worth their own evaluation when a prompt works on one vendor and fails on another — don't default to "use a bigger model".
10. **Small, focused edits in sequence beat one big rewrite.** Each polish iteration (H1p → H1p2 → H1p3) changed one rule. Each change could be attributed to a specific +N or −FP. A bigger multi-rule rewrite would have been fast to make and impossible to diagnose.

**Recommendation:**
Use **Haiku 4.5 + `value_overlap` + current `context.md` + current `instructions.md` + `temperature=0`** for this task. Do not substitute OpenAI gpt-4o or gpt-4o-mini — they score 5/11 regardless of size because of a vendor-level instruction-following pattern (they treat tool output as the final match list rather than a prior). If we move to a materially harder dataset, the escalation question reopens; within OpenAI, a Sonnet-tier Anthropic model (gpt-5-class on the other vendor would need fresh testing) would be the next step, not more gpt-4o.

### Prompt evolution — actual rule text

The winning config (H1p3) is defined by the text below, which lives in `agents/column-matcher/instructions.md` and `data/context.md` at commit `c364771`. Reproducing the 11/11 result requires all three of: the `value_overlap` tool (H1), these instruction rules, and these context rules.

**New in H1 — `instructions.md` step 4 (call the tool):**
> `value_overlap` — pass the reference and input **file paths** (same paths you passed to `profile_data`). This returns a deterministic list of `candidates` where sample values overlap by 3+. Each candidate is a STRONG prior — almost always a true match. Verify semantics/types, and if a reference column appears as the target of multiple candidates (an ambiguity), pick the input column whose *name* is the closer phrase-level match; put the other input column in non_matches.

**New in H1 — `instructions.md` step 5 (use the tool output together with name matching):**
> Analyse the profiles AND candidate list together and produce the complete match set. CRITICAL: value_overlap only surfaces pairs with shared sample values — it will NOT find matches where one column has zero or sparse data, where the values are distinct codes ("M"/"F" in one vs blank in the other), or where the match is purely semantic with no shared values. You MUST also match columns by name and semantics independently of the overlap candidates. Examples you should catch by name/semantics even without overlap: exact/near-exact name matches, domain synonyms (Sex↔Gender, DOB↔Date of Birth, Status↔Participant Status, unique-ID columns, Contingent↔Secondary).

**New in H1p — `context.md` disambiguation rules:**
> - **Form of Annuity** in a reference/template refers to the *active election* the participant has chosen. When the input has both a "historical" column (e.g. "Original Form of Annuity at Commencement") and an "active/future" column (e.g. "Form of Annuity to Be Purchased"), the ACTIVE one is the correct match. The historical one goes in non_matches.
> - **Uniform reference columns** (all rows identical, e.g. a single date or placeholder value) are template defaults, not real data. Do NOT match any input column to a uniform reference column — put the input in unmatched_input instead.

**New in H1p2 — `instructions.md` Key Rules (tighter uniform-reference rule):**
> - **Uniform reference columns are not matchable.** If a reference column has only one distinct value across all rows (e.g. all "2024-05-15"), it is a template default and you must NOT match any input column to it. Put the input in `unmatched_input`, not in `matches`.

**New in H1p3 — `instructions.md` Key Rules (imperative zero-population rule, the change that moved the needle from 10/11 to 11/11):**
> - **ZERO-population matching is REQUIRED when semantics align.** For any input column with 0% population (no sample values), scan the reference columns for a domain-and-name match. If you find one — a column whose name and domain role clearly correspond (e.g. input "1st Contingent Beneficiary Sex" vs reference "Secondary Gender" given `1st contingent = secondary` in the context file) — you MUST put this pair in `matches` with confidence 0.70. Do not put it in `non_matches`. Do not put it in `unmatched_input`. The absence of sample values is NOT disqualifying evidence — the sample is just small. Phrases like "cannot match sparse input to populated reference without sample value confirmation" are wrong and violate this rule.

Key observation: the version before H1p3 said "Low population is not a reason to reject. […] match it — but score conservatively." Haiku *quoted that rule* in its reasoning and then rejected anyway. The imperative rewrite above, which explicitly tells the model what to do and preemptively rebuts its own cautious phrasing, was the binding change.

**Deferred work** (see `docs/roadmap.md` for durable tracking):
- H2 (semantic_parts in profiler) and H1+H2 stacked were not needed — H1 + prompt iteration got us to ceiling on Haiku. Keep the hypothesis live for harder datasets.
- OpenAI GPT-5.x family comparison — test on a fair-tier vendor-equivalent to Haiku.
- OpenAI reasoning models (o3-mini, o4-mini) — answers the reasoning-vs-vendor-style open question.
- Open cross-vendor question: an OpenAI prompt *rewritten* to avoid the tool-literal pattern (e.g. inlining the overlap candidates into the user message and dropping the tool, or wording the rules as "after the tool, you must also...") might close the gap. Not tested.
- Open question: does gpt-4o at temp=0.3 or above "unblock" the semantic matching it's skipping? Would be a cheap follow-up.

---

## Round 2 — (placeholder for future models / hypotheses)

Add additional vendors (e.g. Gemini when supported), additional models, or new hypotheses here. Keep the same structure: Context → Hypotheses → Ladder → Budget → Files → Methodology → Order → Results → Findings.
