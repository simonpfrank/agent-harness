# Product Requirements Document — Agent Harness

## Background

This project follows four previous attempts at building an agent framework, each of which grew too complex to maintain: LangChain wrappers, async architectures, feature creep. The lesson each time was the same — the framework became the problem. This attempt starts from the other end: what if agent behaviour lives in markdown files and the runtime is as small as possible?

## Problem Statement

There are many good tools for building AI agents (see [Appendix: Alternatives Considered](#appendix-alternatives-considered)). They range from full frameworks like LangChain to lighter libraries like smolagents. They all work. But they all require you to define agent behaviour in code, which means you need to understand the framework to build, modify, or even read an agent.

This project takes a different approach: define what an agent does in plain English markdown, keep the runtime minimal, and make the agent folder portable — copy it, git-push it, hand it to someone, and it just works.

The focus is multi-turn, tool-using agents — tasks that are too complex for a single API call or a bash script, and that you do more than once, making it worth writing the instructions. If the task is a one-liner, use curl. If it needs judgment, memory, and multiple steps, that's where this earns its keep.

It may turn out this approach has limits. That's fine — it's worth exploring. The design choices are:

1. **Markdown as the primary definition** — not Python, not YAML
2. **Multi-step agents with tools** — not just prompt patterns
3. **Portable folder format** — copy it, share it, version it
4. **Minimal runtime** — under 500 lines, easy to read and resume
5. **Model-agnostic** — swap providers by changing one line in config

## Vision

An agent is a folder of markdown files. The Python runtime is small and generic. Anyone can read what an agent does, create a new one by writing prose, and share agents by copying folders.

## Target Users

1. **Primary**: People who build reliable automation and want an LLM to handle the parts that need judgment — parsing unstructured data, making decisions, understanding natural language
2. **Secondary**: Developers who want something minimal and readable
3. **Tertiary**: Anyone curious about AI agents who doesn't want to learn a framework

## Core Concept — Agent as a Folder

An agent is defined entirely by files in a directory:

```
my-agent/
  instructions.md     # What this agent does and how (system prompt)
  tools.md             # Available tools and when/how to use each (optional)
  config.yaml          # Model, provider, budget, permissions (~5 lines)
```

- `instructions.md`: The agent's behaviour, written in plain English.
- `tools.md`: Guidance on tool usage — when to use each tool, common patterns, gotchas. Turns a bag of tools into a skill.
- `config.yaml`: Minimal configuration — which model, which provider, budget limits.

Want a new agent? Write markdown. Want to change behaviour? Edit markdown. Want to share an agent? Copy the folder.

## Design Principles

These apply across every feature and decision:

1. **Don't reinvent the wheel.** If there's an existing standard or convention for something, use it. If a library solves a problem well, use it rather than building our own. Agent folder structure borrows from Fabric's patterns. Tool schemas follow the OpenAI/Anthropic JSON schema standard. If a community convention emerges for something like skills or agent configs, adopt it.

2. **Easy to contribute to at any level.** The project should be structured so that someone can contribute a new provider, a new tool, a new loop pattern, or a new example agent without understanding the whole codebase. Each contribution is a self-contained file that plugs in. No provider needs to know about other providers. No tool needs to know about other tools. If there's no Ollama interface, someone can build one and it slots in without touching existing code.

3. **Flat, not layered.** Features are files, not layers. Nothing wraps anything else. The dependency graph is shallow — most files only know about the core types (`Response`, `ToolCall`). This means the project can grow through contributions without becoming tangled.

4. **Markdown over code for behaviour.** If something defines *what an agent does*, it belongs in markdown. If something defines *how the runtime works*, it belongs in Python. The Python should rarely need changing; the markdown is where users and contributors spend their time.

5. **Deterministic where it matters.** Budget enforcement, security guardrails, and permission checks are deterministic code, never LLM-decided. The LLM handles judgment; the harness handles safety.

## Functional Requirements

### FR1: Agent Execution
- Load an agent from a folder (read config.yaml, instructions.md, tools.md)
- Run a ReAct loop: send messages to LLM, execute tool calls, feed results back
- Support different loop patterns as the project matures (plan-and-execute, research, etc.)
- Agents can be run interactively (REPL) or as a single command (CLI)

### FR2: Provider Abstraction
- Support multiple LLM providers through a single interface: `chat(messages, tools) -> Response`
- Each provider is a standalone file (~60 lines) that translates to/from the common format
- Adding a new provider = writing one file with one method
- Start with Anthropic (Claude), add OpenAI and local models (Ollama, LM Studio) progressively
- Provider-specific features accessible via pass-through kwargs (don't abstract away useful capabilities)

### FR3: Tools
- Tools are plain Python functions with type hints and docstrings
- JSON schemas auto-generated from function signatures (no manual schema writing)
- Built-in tools: run_command, read_file, execute_code, save_memory, recall_memory, list_memories, run_agent, handoff_agent
- Tool registry is a simple dict mapping name to callable
- **Custom tools** live in a project-level `tools/` directory (one function per `.py` file)
- Custom tools are discovered at startup but only available if listed in agent's config.yaml `tools` list
- Built-in tools cannot be overwritten by custom tools with the same name
- No third-party tool marketplace — you write it, you own it

### FR4: Skills
- A skill = markdown knowledge + optional scripts describing how to approach a task
- Skills live in `{skill_name}/SKILL.md` directories, optionally with `scripts/`
- **Shared skills** in project-level `skills/` directory — available to all agents
- **Agent-local skills** in `{agent_dir}/skills/` — override shared skills on name collision
- Skills are auto-loaded into the system prompt (no config needed — presence = active)
- Skills are NOT tools — they describe *how* to use tools effectively
- Scripts within skill folders are invoked by the agent via run_command/execute_code
- No community skill contributions — you write your own

### FR5: Budget and Cost Control
- Turn counter with configurable maximum (hard stop)
- Token usage tracking per turn and cumulative
- Cost calculation per provider (each provider knows its own pricing)
- Configurable cost ceiling (e.g. max_cost_gbp: 0.50)
- Hard stop at budget limit with progress summary — agent reports what it's done so far
- All budget logic is deterministic — no LLM decides when to stop spending

### FR6: Security and Guardrails
- **Tool approval**: Before executing any tool, show the user what will run. Options: approve once, approve for session, approve persistently per workspace folder
- **No shell=True**: All subprocess calls use argument lists
- **Input validation**: Validate tool arguments (path traversal, suspicious patterns)
- **Deterministic hooks**: Pre/post execution checkpoints where deterministic code runs — not LLM-decided
  - `before_tool_exec`: Permission check, dangerous command blocking, input validation
  - `after_tool_exec`: Output sanitisation, prompt injection scanning
  - `on_external_content`: Injection detection before content enters conversation
- **Prompt injection defence**: Deterministic scanner for known injection patterns in tool outputs, file content, and web content. Suspicious content quarantined with warning labels.
- **No network exposure**: Runs locally, talks to APIs over HTTPS. No daemon, no WebSocket server, no pairing.
- **Secrets**: API keys from environment variables only, never in config files. Config files safe to commit.

### FR7: Memory
- **Conversation memory**: The message list. Dies when session ends.
- **Session persistence**: Save/load conversations as JSON files. Resume later.
- **Long-term memory**: Markdown files in a `memory/` folder within the agent directory. Tools to save and recall. Start with key-based lookup, graduate to embedding search (RAG) if needed.
- Memory is just files + tools to read/write them — not a separate subsystem.

### FR8: Multi-Agent
- An agent can be a tool for another agent. No new abstraction needed.
- An orchestrator agent calls specialist agents by invoking them as tool functions.
- Each sub-agent can use a different provider/model (cheap models for grunt work, capable models for orchestration).
- Agents can also invoke each other via CLI (one agent runs another as a subprocess command).

### FR9: CLI and REPL
- **Single command mode**: `python -m agent_harness run <agent_folder> "prompt"` — run once, return result
- **Interactive REPL**: `python -m agent_harness run <agent_folder>` — conversational mode
- Start with basic `input()` + Rich formatting
- Graduate to cli-repl-kit integration for polished experience (tab completion, key bindings, etc.)
- The agent doesn't care what calls it — `agent.run(message) -> str` works for REPL, CLI, tests, and future API

### FR10: Routing
- An agent can route work to other agents or tools based on the task
- Routing can be LLM-decided (the orchestrator reads the request and picks the right sub-agent) or rule-based (deterministic routing in a hook based on keywords, file types, etc.)
- Example: a triage agent receives a request, decides it needs research → routes to research agent. Research agent finds a CSV → routes to data-analysis agent.
- Routing is not a separate subsystem — it emerges from the combination of:
  - **Agent-as-tool**: one agent invokes another as a function call
  - **Instructions**: the orchestrator's `instructions.md` defines routing logic in plain English
  - **Deterministic hooks**: `before_tool_exec` can intercept and reroute based on patterns
- Multi-hop routing works naturally because each agent is independent
- Routing decisions are visible in the tool call log — no black-box dispatching

### FR11: Agent Building
- A user (or an AI assistant like Claude Code) can create a new agent by describing what it should do
- The harness scaffolds the agent folder: generates `instructions.md`, `tools.md`, `config.yaml`
- If the agent needs tools that don't exist yet, they get written as Python functions and added to the tool library
- If the agent needs specific scripts or data files, they get added to the agent folder
- The agent folder grows organically — start with a basic config, add tools and instructions as needs emerge
- Claude Code (or any coding assistant) can build agents because the format is just markdown + YAML + simple Python functions — no framework knowledge needed

### FR12: Deterministic Code Execution
- Agents should prefer running code to get deterministic answers rather than having the LLM analyse data directly
- `execute_code` tool runs Python/bash snippets with timeout and output capture
- This is how questions like "how many rows in this CSV?" get reliable answers
- Sandboxed: working directory isolation, timeout enforcement, output size limits

## Non-Functional Requirements

### NF1: Elegant Simplicity
- The goal is least work, least friction, least surprise. Someone reads the code and thinks "I can use that."
- Minimalism is a rigorous design goal, not a vague aspiration. Every line of code must justify its existence.
- Any file can be understood in isolation — no deep dependency chains
- Flat architecture: features are files, not layers. Every feature is inert by default and activates through config — no None checks, no conditional imports.
- No file imports more than 2 other internal modules
- If you're writing Python to define agent behaviour, you're doing it wrong — it belongs in markdown

### NF2: Readability
- A stranger can read an agent's `instructions.md` and understand what it does in under 2 minutes
- The Python codebase is small enough to read entirely in 15 minutes
- Example agents are the primary documentation

### NF3: Extensibility and Contribution
- Anyone can contribute at any level without understanding the whole codebase:
  - **New provider**: one file in `providers/`, implements `chat()`. No other files change.
  - **New tool**: one function with type hints. No other files change.
  - **New loop pattern**: one function. Minimal registration in run.py.
  - **New example agent**: a folder with markdown + config. No code changes at all.
  - **RAG**: it's a tool. No core changes.
  - **MCP**: a tool source adapter. No core changes.
  - **HTTP API**: a new entry point that imports the agent. No core changes.
- Each contribution is self-contained and testable in isolation
- The project grows through addition, not modification

### NF4: Reliability
- Budget enforcement is deterministic — never exceeded
- Hook-based guardrails are deterministic — never bypassed
- Agents that hit limits stop gracefully with a progress report
- All errors are caught and reported, never silently swallowed

## Out of Scope (Backlog)

- GUI of any kind
- Real-time collaboration
- Replacing Claude Code for coding tasks
- MCP server/client support (future — compatible by design)
- HTTP API (future — the function interface supports it)
- Streaming responses (future — provider interface designed to allow it)
- OpenRouter and provider aggregators (future)
- Proactive/scheduled agents (future)
- Agent sharing registry / hub (future)

## Success Metrics

1. v1 is buildable in a single 2-3 hour session
2. An agent folder is understandable by a non-technical person
3. The harness runs reliably for extended automated tasks without runaway costs
4. The codebase is small enough that resuming after weeks away takes minutes, not hours
5. Example agents solve real, practical problems (not just demos)

---

## Appendix: Alternatives Considered

There are excellent tools available. This section documents what exists and how this project relates to them.

### Frameworks (agent behaviour defined in code)

| Tool | Scale | Strengths | Trade-off for this use case |
|------|-------|-----------|---------------------------|
| **LangChain** | ~100k+ LOC | Most complete ecosystem, every integration | High complexity. Simple tasks need many concepts. |
| **CrewAI** | ~15-25k LOC | Intuitive role model, YAML config for agents | Tools and orchestration still need Python. |
| **AutoGen** (Microsoft) | ~30-50k LOC | Sophisticated multi-agent, Studio GUI | Heavy. Studio is a full web app. |
| **Semantic Kernel** (Microsoft) | ~50k+ LOC | Enterprise-grade, multi-language | Overkill for simple automation. |
| **LlamaIndex** | ~80k+ LOC | Best-in-class RAG | Agent support feels secondary to retrieval. |
| **Haystack** (deepset) | ~40-60k LOC | Clean pipelines, production-grade | Agents secondary to pipeline abstraction. |
| **smolagents** (HuggingFace) | ~3-5k LOC | Genuinely simple, code-based tool execution | Still Python-defined. HF ecosystem tie-in. |
| **pydantic-ai** | ~5-8k LOC | Excellent type safety, clean API | Code-first. Behaviour lives in Python, not config. |
| **mirascope** | ~4-6k LOC | Pythonic, low abstraction | Code-first. Smaller community. |
| **phidata/agno** | ~8-15k LOC | Simpler than LangChain, good defaults | Code-first. Growing toward complexity. |

These are all good at what they do. The common trade-off: you need to write and understand Python (or the framework's abstractions) to define agent behaviour.

### Platforms (GUI/config-defined, not portable)

| Platform | Strengths | Trade-off |
|----------|-----------|-----------|
| **Dify** | Non-developers can build agents, self-hostable | Platform lock-in. Need Dify running. Not a folder you can share. |
| **Flowise** | Easy visual building | LangChain dependency. Not portable. |
| **Langflow** | Intuitive flow design | Same platform lock-in. |

### Closest to this approach

| Project | What it does well | Where it differs |
|---------|------------------|-----------------|
| **Fabric** (Daniel Miessler, ~25k stars) | Agents as `system.md` in portable folders. Clean, simple. | Single-turn patterns only — no tool use, no multi-step, no state. |
| **OpenClaw** (~250k stars, 2026) | Proved markdown-as-agent-definition works (`SOUL.md`, `AGENTS.md`). 100+ skills, 25+ messaging platforms. Pluggable ContextEngine. | Network daemon with documented security vulnerabilities (OWASP flagged). Very different scope — full personal assistant platform, not a minimal framework. |
| **Hermes Agent** (Nous Research, 2026) | Self-improving skills system — agent synthesises completed tasks into reusable skill documents. Cross-session memory with FTS5 recall. Multi-platform messaging (Telegram, Discord, Slack, WhatsApp). 40+ built-in tools. 5 deployment backends (local, Docker, SSH, Singularity, Modal). | Much larger scope. Skills self-improvement is genuinely novel — our agents don't learn from experience. Multi-platform messaging is a different product category. |
| **Paperclip** (~30k stars, March 2026) | Multi-agent orchestration as a company. Org charts, budgets, governance with approval gates, immutable audit trails, config rollback. File-based agent communication. Agents run on Claude Code/OpenClaw/Codex. Heartbeat scheduling. Multi-company isolation. | Fundamentally different scope — it's a management layer for agent teams, not an agent runtime. Node.js + React + Postgres. Requires existing agent infrastructure (Claude Code, OpenClaw). The corporate hierarchy metaphor is the innovation. |
| **Claude Code** | `CLAUDE.md` files shape behaviour beautifully. | Locked to Claude Code. Not a general-purpose runner. |
| **Cursor / Windsurf** | `.cursorrules` markdown files for behaviour. | Locked to their IDEs. |

Fabric is the nearest neighbour — it shares the "agent is a folder of markdown" philosophy. The difference is that Fabric handles single-turn prompt patterns, while this project aims for multi-step agents with tool use and state.

**Notable features from competitors worth considering:**

| Feature | Source | Relevance to us |
|---------|--------|-----------------|
| **Self-improving skills** | Hermes Agent | Agent completes a task, synthesises the approach into a reusable skill document (structured markdown). Next time, loads the skill instead of solving from scratch. Reported 40% speedup on repeated tasks. Could fit our agent-as-folder model — a `skills/` directory with markdown files the agent loads. |
| **Pluggable ContextEngine** | OpenClaw | Custom context management strategies without altering core. We have basic context trimming; a pluggable strategy would allow RAG, summarisation, or sliding window approaches. |
| **Model fallback chains** | OpenClaw | Automatic failover to secondary provider on rate limit. We retry same provider; chaining to a fallback model would be more resilient. |
| **Natural language cron** | Hermes Agent | Schedule agent runs in plain English ("every morning at 8am, summarise my inbox"). We have no scheduling. |
| **Multi-platform messaging** | Hermes, OpenClaw | Both support 10+ messaging platforms. Out of scope for us but validates the agent-as-folder portability concept — the agent definition is platform-independent. |
| **Immutable audit trail** | Paperclip | Append-only log of every tool call, API request, and decision. Cannot be edited or deleted. We have trace files (JSONL) but they're not append-only or tamper-evident. |
| **Governance with approval gates** | Paperclip | Consequential actions (hiring agents, strategy changes) require board/human approval. Enforced by architecture, not convention. Our permissions system is per-tool; Paperclip's is per-decision-type. |
| **Config versioning with rollback** | Paperclip | Agent config changes are versioned. Bad changes can be rolled back. We have no config history. |
| **Cost tracking per agent/task/project** | Paperclip | Granular cost attribution. We track per-agent budget but not per-task or per-project. |
