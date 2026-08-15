# Multimodal / file handling — PRD

**Status:** Shipped 2026-08-15. See "Multimodal file handling" in `docs/roadmap.md`'s Done section for the summary; the implementation plan section below is the as-built spec (validated by a Plan agent before building, two real bugs caught and fixed as part of the same pass — see that entry).
**Parent roadmap item:** "Image handling — send and receive encoded images" in `docs/roadmap.md` (Plausible Future Capabilities) — this document supersedes that entry's scope, broadened from "images" to "images, documents, and files" during requirements discussion.

Purpose: capture what this capability needs to do and not do, and the policy
decisions behind it, before moving to a technical spec. Mechanism-level
detail (exact type changes, function signatures, provider-branch code shape)
is deliberately left to the spec phase, not decided here.

## Context

Checked directly before scoping, not assumed:

- `Message.content` is `str | None` today — no image/document content-block
  support anywhere in either provider (`_to_anthropic_messages`,
  `_to_openai_messages`/`_to_openai_input`). This is the gap.
- `tools/profile_data.py` already reads `.csv`/`.xlsx`/`.xls`/`.xlsm` via
  `pandas.read_excel`/`read_csv`, registered as an ordinary discovered tool.
  Confirms one whole category of "file input" (tool-mediated binary formats)
  is already architecturally solved — the pattern is "write a tool," not
  new harness plumbing.
- Both providers' current APIs support the model-native binary types this
  scopes to, verified live via Context7, not from training memory:
  Anthropic has `DocumentBlockParam` (`type: "document"`) for PDFs plus its
  existing image blocks; OpenAI's Responses API (already the harness's
  default hosted-OpenAI path) has `input_file`/`input_image` content types.
- `agent_harness/tools.py::execute_tool` already truncates tool output at
  `max_output_chars` (default 10,000) — directly relevant, since a
  base64-encoded file would be silently corrupted by this if not accounted
  for.
- `path_traversal_detector` (`hooks.py`) already exists and guards tool
  arguments named `path`/`working_dir`/etc. against escaping the workspace
  root — reusable for guarding saved-file names rather than building new
  path-safety logic from scratch.
- `eval/runner.py::_clear_memory` already establishes the precedent of
  clearing a per-agent directory at the start of a run for a "fresh state,
  no accumulation" reason — reusable pattern for the tmp/output directory
  below, rather than a new idea.
- `agents/*/logs/` already demonstrates what happens when a directory is
  never cleared: dozens of timestamped files accumulating indefinitely,
  going back months. Concrete cautionary example, not hypothetical, for why
  the tmp/output directory design below clears rather than nests-forever.

## Scope

### Already solved, not new work — stated explicitly so it isn't rebuilt

- **Text files** (`.csv`, `.md`, `.txt`, etc.) — `read_file` already handles
  these.
- **Binary formats a tool can parse** (`.xlsx` via `profile_data.py`, and
  the same pattern for anything else) — write a tool, following existing
  `discover_tools` conventions. No harness changes needed.
- **Tool-returned structured/large text data** (e.g. a hypothetical SQL
  tool returning CSV) — already flows through the ordinary
  `ToolResult.output: str` path like any tool result. Only relevant
  open question is whether `max_output_chars` truncation needs revisiting
  for this case — a tuning question, not a design gap.
- **Image/chart generation** — already possible via `execute_code`
  (e.g. a matplotlib script writing a PNG to disk). This PRD does not add
  generation capability; it adds the ability for the agent to *look at*
  what it (or a tool) produced.

### New work — what this PRD actually scopes

1. **Model-native binary input (vision + documents).** Images and PDFs
   specifically — the two content types both providers currently support
   natively. A path-based tool (e.g. `view_image(path)` / `view_document(path)`)
   reads the file, detects MIME type, base64-encodes it, and the harness
   constructs the correct provider-specific content block for the *next*
   message so the model actually perceives it — not just reads a text
   description.
2. **Agent-produced binary output.** A tool that creates new binary content
   (not already a file on disk) can hand it back via a convention — embed
   base64 + a filename in its ordinary string output — and the harness
   detects this, decodes it, validates it, and writes it to disk. The tool
   author does not need a new `ToolResult` shape for this; existing tools
   that already write directly to disk (e.g. `execute_code` writing a PNG)
   don't need this convention at all — they just return the plain path.
3. **A per-agent scratch directory** for saved/generated files (see Output
   storage below).

### Explicitly out of scope

- **Image/file *generation* via a dedicated API** (DALL·E, etc.) — the
  matplotlib/`execute_code` pattern already covers this need; a generation
  API is a different capability, not requested.
- **Audio or video content** — not raised, not scoped.
- **CLI clipboard paste.** Terminals are text streams; there is no
  standard mechanism for a line-buffered prompt to receive clipboard image
  data. A real equivalent is buildable (an explicit trigger that shells out
  to a platform clipboard tool — `pngpaste` on macOS, `xclip`/`wl-paste` on
  Linux, PowerShell's clipboard API on Windows) but it needs the same
  raw-terminal-mode input layer already scoped separately for two other
  roadmap items (no-Enter-keypress prompts, live `#` tool-invocation
  filtering) — bundle with that work when it happens, not this one.
- **A generic "read any binary format" tool.** Wrong pattern — purpose-built
  tools per format (matching `profile_data.py`) is how this harness already
  does it, and stays how it should.
- **Eval framework support for grading binary/image output.**
  `eval/graders/code/` already supports arbitrary custom code graders,
  auto-discovered exactly like tools — someone who needs binary-aware
  grading writes one. No generic model-graded-vision capability is being
  built. Zero new eval-framework code either way; this is a scope decision,
  not a build item.
- **Modifying `write_file`/`edit_file`.** These stay text-only, unrelated
  to the new binary-output convention above.

## Policy decisions

These were the open questions raised during scoping; each has a decided
default now.

### Provider/model capability checking — no static compatibility table

Deliberately **not** pre-validated against a harness-maintained "which
models support vision/documents" list. Direct parallel to a real bug fixed
earlier this project: `budget.py::COST_TABLE` had a stale, silently-wrong
entry because a hand-maintained compatibility table drifted from reality.
A second one for vision support would be the same failure shape waiting to
happen again. Instead: let the provider API be the source of truth. If a
model can't handle a content type, the API rejects it and that error
surfaces normally, same as any other provider-side rejection today (via
the existing `with_retry`/exception path in `providers/*.py`). If a model
handles something better than expected, that's fine too.

One thing to verify during the spec/build phase, not decided as policy:
the rejection surfaces one turn *after* the tool call that read the file
(the tool itself does no API call — the failure happens when the harness
sends the resulting content block to the model on the next `chat_fn`
call). Needs confirming this degrades as a clear error rather than
crashing the loop/REPL.

### Token/context cost — two separate mechanisms, not one

These were initially conflated during scoping and need to stay distinct:

- **Output (agent-produced files):** extraction happens synchronously at
  tool-call time. Raw base64 never enters `Message` history at all — no
  pruning mechanism needed for this path, it's clean from the start.
- **Input (model views an image/document):** the content block genuinely
  has to exist in at least one real message for the model to perceive it,
  and it *will* be resent on every subsequent turn like the rest of
  history unless pruned. **Default policy: keep only the most recently
  viewed image/document "live" in history.** Once a newer one is viewed
  (or the turn ends), replace the older content block with a short text
  reference (e.g. `"[viewed: chart.png]"`) — the file stays on disk, and
  the model can call `view_image` again if it genuinely needs to look a
  second time. This reduces both cost and context-window usage, unlike
  provider-side prompt caching alone (which reduces cost but the content
  still counts against the context window).
- **Prompt caching** (`docs/roadmap.md`, currently delayed) is a
  complementary, not competing, lever — multimodal content is a stronger
  case for revisiting it than plain text ever was, since an image block is
  exactly the large, static, repeatedly-resent payload caching exists for.
  Not part of this PRD's build, just noted as newly more relevant.

### Output storage — flat per-agent scratch dir, cleared per run

`agent_dir/tmp/` (naming TBD at spec time), cleared once at the start of
each run — inside `prepare_runtime()`, before the first turn, mirroring
`eval/runner.py::_clear_memory`'s existing "fresh state" pattern. Not
per-turn (nothing disappears mid-conversation), not session-ID-nested (no
reliable session-ID concept exists today — sessions are optionally
user-named via `--session`, not auto-generated). Chosen specifically to
avoid the accumulation problem `agents/*/logs/` already demonstrates in
this repo. Gitignored, same as `logs/`/`sessions/`/`memory/`.

### Guardrails on agent-produced binary output

Before writing anything decoded from a tool's embedded base64+filename
convention:
- Sanitize the filename against path traversal — reuse
  `hooks.py::path_traversal_detector`'s existing logic rather than write
  new path-safety code.
- Cap decoded size.
- Validate the decoded bytes' actual file signature against the claimed
  MIME type, rather than trusting a tool's claim blindly.
- Confirm the existing `max_output_chars` truncation in `execute_tool`
  does not run before this extraction — it would silently corrupt a
  base64 payload otherwise. This is a real bug to fix as part of this
  work, not a hypothetical.

### CLI display

Raw base64 must never reach the terminal (`display.py::show_tool_result`/
`show_response`) — for a different reason than the context-cost point
above (readability, not cost), but solved by the same discipline: extract
the real content and replace it with a short reference as early in the
pipeline as possible, before it's ever rendered or persisted.

### Provider size/dimension/page limits

Both providers cap file size (images) and page count (Anthropic PDFs).
Default for this pass: reject with a clear tool error if a file exceeds
provider limits. No auto-resize/auto-split logic — a real feature if
needed later, not assumed necessary now.

## Worked example (validates the design end-to-end)

Agent analyzing sales numbers, asked to produce and sanity-check a chart:

1. **Generate:** agent calls `execute_code`, which runs a matplotlib
   script and writes `chart.png` to the scratch directory. Tool returns a
   plain text path — no base64 involved, the file's already on disk.
2. **Verify:** agent calls `view_image("chart.png")`. The harness reads
   it, base64-encodes it, and attaches a real image content block to the
   next message — the model genuinely sees the chart (legible labels,
   correct data) rather than just trusting the script exited cleanly.
3. **Iterate:** if it looks wrong, agent adjusts the script, regenerates,
   calls `view_image` again — ordinary sequential tool calls, nothing
   additional needed. The pruning policy above means only the most
   recently viewed chart stays as a live image block in history; earlier
   attempts collapse to a text reference.

This is deliberately a two-step, explicit pattern (generate, then
separately decide to look) rather than auto-attaching every image a tool
writes — keeps the agent (via its own instructions) in control of when
the vision cost is worth paying, and keeps the harness simple. Revisit
only if it proves too clunky in practice.

## Next step

Move to spec + plan per the project workflow — technical design for the
`Message`/`ToolResult` shape changes, provider-specific content-block
construction code, the `view_image`/`view_document` tool implementation,
and test plan (unit + a real end-to-end verification run, matching how
every other feature this project has shipped was verified).
