# RAG — Roadmap

**Status:** Design captured, nothing built yet.
**Parent roadmap item:** `RAG framework/tools` in `docs/roadmap.md`.

Purpose: capture where RAG lives in the harness, how it's delivered to the
model, which provider it defaults to, and a phased build order — start small
(plain text, one delivery mechanism, one provider) and only take on the hard
parts (PDF mining, multimodal, a second provider) when there's an actual
reason to.

## Context

Verified before any of this was designed: zero existing RAG/embedding/
vector-store code anywhere in the repo. `agent_harness.providers.registry`
only exposes `chat()` — no `embed()`. The only "structured data" tooling that
exists (`profile_data`, `value_overlap`, project-level `tools/`) is CSV/Excel
specific, built for column-matcher, not a general capability.

## Delivery — two mechanisms, sharing one provider layer

**Default: RAG as a tool.** A tool function (e.g. `tools/rag_search.py`,
following the existing one-file-one-function `discover_tools` convention —
zero framework changes needed) that the agent calls when it decides it needs
more context. Matches how `value_overlap`/`profile_data` already work.
Advantages over always-on injection: the agent skips retrieval when it
doesn't need it (saves cost/latency), and it requires no core changes at all.

**Opt-in: config-driven pre-loop injection, for a dedicated "knowledge
agent" persona.** A `rag:` block in `config.yaml` that causes
`runtime.prepare_runtime`/`init_messages` to run retrieval in Python *before*
the loop starts and inject results into the system prompt — **not** by
forcing a tool call through the reactive loop. Forcing a tool call keeps
every disadvantage of the reactive path (framed as an ambiguous tool result
rather than authoritative context, subject to the generic
`max_output_chars` truncation in `tools.py::_truncate` rather than
RAG-aware chunk-budgeting, diluted if other tools run the same turn, costs
an extra round-trip). Pre-loop injection avoids all of that, at the cost of
touching `runtime.py`/`AgentConfig` — a scope and shape comparable to the
`stream`/`show_thinking` config additions already shipped this session, not
a new category of core complexity.

**Both mechanisms resolve through the same provider registry.** A tool can
point at a different provider/db instance than the agent's configured
default — e.g. the agent's default (used for pre-loop injection) is a
general knowledge base, while a specific tool instance searches a different,
specialized index. This is the flexibility the design needs: one shared
interface, multiple configured instances.

## Provider abstraction

Mirrors `agent_harness/providers/` exactly: a registry keyed by provider
name, pluggable implementations behind a shared interface, `config.yaml`
names the provider + connection details.

**Default: Chroma, embedded/local mode** (`chromadb.PersistentClient`).
- No server process — writes to a local directory, same "no infra" shape as
  every other piece of persistence in this repo (`session.py`, `trace.py`,
  `eval/storage.py` are all flat files, nothing here runs a daemon).
- One dependency add, comparable weight to `pandas`/`openpyxl` already added
  for column-matcher tooling.
- Same client API scales from local (`PersistentClient`) to a remote/
  dedicated deployment (`HttpClient(host=...)`) — going to production might
  not even need a different provider *class*, just different connection
  config.

**Second provider, not default: Weaviate**, for anyone who wants
production-grade native hybrid search (vector + BM25, tunable blend) and is
willing to run a server for it — even Weaviate's "embedded" mode runs an
actual local server process, which is why it isn't the default despite
being a genuinely strong option. Same registry pattern: `provider: weaviate`
in config, no framework changes to add it once the abstraction exists.

**Open question, not resolved yet: embeddings provider default.** Chat and
embeddings are different API surfaces even from the same vendor (Anthropic
doesn't offer embeddings natively — common choices are OpenAI's embeddings
API, Voyage AI, or a local model). This needs its own default decision,
parallel to but independent of the chat-provider default. Not decided —
flagged so it doesn't get silently assumed when building Phase 1.

## Multimodal — verified against current docs, not assumed

Chroma's multimodal support (checked live, 2026-08-03): **images only**, via
a built-in `OpenCLIPEmbeddingFunction` (text + images share one embedding
space) plus an `ImageLoader` data loader. Python-only currently. Chroma does
not store original image data — only the embedding — so it re-fetches the
original via the stored URI at query time, meaning the original file has to
stay put wherever it was indexed from.

This is **retrieval-side** multimodal only — "find the image similar to this
query." It says nothing about the model actually *seeing* that image.
**LLM vision remains a fully separate, unbuilt capability** — `Message.
content` is `str | None`, no image content-block support anywhere in either
provider (`_to_anthropic_messages`, `_to_openai_messages`/`_to_openai_input`).
Retrieval and vision are two different pieces of work; building one doesn't
give you the other.

## Phased build order

### Phase 1 — plain text, tool-only, Chroma only (start here)
- Chroma provider, embedded/local mode.
- Ingest: plain text files, chunked, embedded, stored.
- Delivery: tool only (`rag_search`). No pre-loop injection yet.
- Resolve the embeddings-provider default as part of this phase — can't
  ship Phase 1 without picking one.

### Phase 2 — config-driven pre-loop injection
- The `rag:` config.yaml block, `runtime.py` integration, for the dedicated
  knowledge-agent persona. Only worth building once Phase 1's tool path has
  proven the retrieval quality is good enough to trust unconditionally.

### Phase 3 — provider hardening
- Weaviate as a second provider, if/when native hybrid search becomes a
  real requirement rather than a nice-to-have.
- Revisit the Chroma `PersistentClient` → `HttpClient` upgrade path once an
  actual production case exists.

### Phase 4 — multimodal (online content)
- Chroma's OpenCLIP image support, for content where "the image links back
  to a URL" is fine — no local extraction/storage problem to solve.

### Phase 5 — PDF mining (its own subject, decisions deferred to when we get here)
Explicitly not designed now — a whole subject with real decisions to make
at the time:
- Text extraction approach (library choice, quality tradeoffs).
- Whether to also extract embedded images, and if so, storage layout — the
  working idea is a folder beneath the vector db's own directory, with the
  same "if the file's there, great, if not, no drama" failsafe that Chroma's
  own re-fetch-via-URI model already requires.
- Chunking strategy for extracted text.
- Whether to rasterize pages as images for CLIP-indexing vs. text-extraction
  only, or both.

### Not phased — CLI image viewing (cheap, low priority, do whenever)
`rich-pixels` (Unicode half-block rendering, fits the existing `rich`
dependency in `display.py`) behind two failsafes: file-existence check, and
`console.is_terminal` (skip entirely for non-interactive output). Small,
self-contained, doesn't block anything above — see conversation log
2026-08-03 for the full reasoning. The better long-term home for viewing
retrieved images is a browser-based chat client via the (now-shipped) HTTP
API — "here's a retrieved image" is just another SSE event type a browser
client renders properly, no terminal-capability guessing or block-art
fidelity ceiling; the CLI keeps `rich-pixels` as its cheap fallback either
way. Not a reason to build a browser client now — just a data point for
when one exists.

## Adjacent idea — vector db for agent memory (not a commitment)

Raised during this design discussion: `save_memory`/`recall_memory`/
`list_memories` (existing built-in tools) currently persist flat markdown
files under `{agent_dir}/memory/`, read back by the LLM listing/reading
files — no semantic search. Once a RAG provider abstraction exists, the same
infrastructure could plausibly back memory too — embed a memory note on
save, recall via semantic similarity instead of just listing filenames.
Genuinely adjacent (same provider layer), but a separate decision from RAG
proper — memory's current flat-file design was a deliberate choice ("no
automatic memory, the LLM decides what to remember"), and moving it onto a
vector store changes that model's simplicity. Not scoped, not phased —
revisit only if flat-file memory actually becomes a limitation in practice.
