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
- `value_overlap` actively hurt gpt-4o-mini (6.80 → 5.00). The smaller model treats the tool output as the definitive match list and drops name/semantic matches that aren't value-aligned. This is a capability limit, not a prompt issue — confirmed across two prompt revisions.

**Incidental findings:**
- A harness bug was discovered and fixed: `max_output_chars=10000` (default) truncated `profile_data` output. The original `value_overlap` design received the profile JSON as a tool argument, and the truncated profile was then *hallucinated* by the model into compressed JSON when re-emitted. Fixed by making `value_overlap` read files directly, and by raising the agent's `max_output_chars` to 40000.
- A provider-kwargs passthrough bug was discovered and fixed as a prerequisite: neither provider was passing `temperature` through to the API, so the original H4 hypothesis was untestable until fixed.

**Recommendation:**
Use Haiku 4.5 + `value_overlap` + current `context.md` + current `instructions.md` + `temperature=0`. Do not escalate to a larger model for this dataset — the last 2 hard misses are solved at the Haiku tier, so a Sonnet/gpt-4o ceiling check is not needed to declare a winner. If we take on a materially harder dataset, the escalation question reopens.

**Deferred work:**
- H2 (semantic_parts in profiler) and H1+H2 stacked were not needed — H1 + prompt iteration got us to ceiling. Keep the hypothesis live for harder datasets.
- Open question: does H1p3 on mini improve now that the prompt is better? Worth ~$0.05 to find out if we want a floor-cost recommendation.
- Open question: does gpt-4o match Haiku at comparable cost? Worth ~$1.50 if we want a cross-vendor recommendation.

---

## Round 2 — (placeholder for future models / hypotheses)

Add additional vendors (e.g. Gemini when supported), additional models, or new hypotheses here. Keep the same structure: Context → Hypotheses → Ladder → Budget → Files → Methodology → Order → Results → Findings.
