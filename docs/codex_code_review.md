# Codex Code Review

## Summary

The repo has a good core idea and several files are still pleasantly small, but the current implementation has drifted away from its own main promise: a minimal, flat harness where an agent folder behaves consistently everywhere. The biggest problems are not style issues; they are behavior mismatches and global-state shortcuts that will make the harness harder to trust as experimentation grows.

## Findings

- **[critical] Tool approval persistence is documented but not actually implemented end-to-end.** `cli.py` presents `[a]llow once / allow for [s]ession / [d]eny?`, but `_permission_prompt()` collapses both allow options to a plain boolean, so the caller cannot distinguish "once" from "session" ([agent_harness/cli.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/cli.py:136)). `Permissions` has `load()`/`save()` support for persistent approvals, but the CLI never passes a `persist_path` and never calls either method ([agent_harness/permissions.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/permissions.py:76), [agent_harness/cli.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/cli.py:308)). That directly contradicts the PRD promise of "approve once, approve for session, approve persistently per workspace folder" ([docs/prd.md](/Users/simonfrank/Documents/dev/python/agent-harness/docs/prd.md:108)).

- **[critical] `run_agent` sub-agents do not run with the same behavior as standalone agents, so "agent as folder" is not consistently true.** Standalone execution builds the full system prompt from `instructions.md`, optional `tools.md`, and loaded skills ([agent_harness/cli.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/cli.py:118)). `routing.run_agent()` only injects `config.instructions`, silently dropping `tools.md` and all skills ([agent_harness/routing.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/routing.py:80)). It also skips the CLI runtime wiring entirely: no hooks, no permissions, no tracing, no tool reconfiguration ([agent_harness/routing.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/routing.py:14)). Because tool settings live in process-global module variables such as `memory_dir`, `tool_timeout`, and `active_executor` ([agent_harness/memory.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/memory.py:10), [agent_harness/tools.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/tools.py:19), [agent_harness/tools.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/tools.py:196)), a sub-agent can inherit the parent agent's runtime settings and memory location instead of its own. This is the opposite of simple and predictable.

- **[warning] The path traversal hook is both too blunt and too weak.** `path_traversal_detector()` blocks any tool call whose argument values contain the literal substring `..` ([agent_harness/hooks.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/hooks.py:64)). That means legitimate free-form text or code can be rejected for containing `..`, while absolute paths and other non-`..` escapes are still allowed. So the hook creates false positives without providing real path containment. For a project that wants deterministic safety without deliberate complexity, this is a poor trade-off.

- **[warning] Optional provider dependencies are imported eagerly, which makes the CLI more coupled than it needs to be.** `agent_harness.providers.__init__` imports both provider modules up front ([agent_harness/providers/__init__.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/providers/__init__.py:7)), and `cli.py` imports that registry at module import time ([agent_harness/cli.py](/Users/simonfrank/Documents/dev/python/agent-harness/agent_harness/cli.py:26)). In the project virtualenv this works, but it still means argument parsing and `init` are unnecessarily tied to provider SDK availability. For a harness that wants a tiny, flat composition root, lazy provider loading would be cleaner.

## Architectural Drift

- The docs repeatedly sell "small, flat, easy to read" as the defining feature, and that is the right bar.
- The current codebase is drifting away from that bar in the composition layer:
  - `agent_harness/cli.py` is 362 lines.
  - `agent_harness/tools.py` is 309 lines.
  - `agent_harness/types.py` is 92 lines despite the docs repeatedly framing it as the tiny immutable root.
- More important than raw size, the runtime now depends on mutable module globals (`memory_dir`, `tool_timeout`, `active_executor`, routing depth), which is exactly the kind of hidden coupling that turns a simple harness into a framework.

## Recommendations

- Make permissions honest and small: either implement the three approval modes fully, or cut the claim and UI down to the two modes that really exist.
- Introduce a tiny immutable runtime/context object for per-agent execution state instead of mutating module globals. That single change would simplify routing, memory isolation, and executor selection.
- Refactor sub-agent execution to reuse the same prompt-building and callback wiring path as standalone execution. If an agent folder is portable, it must behave the same whether launched from CLI or as a tool.
- Replace the current path traversal string check with path-based validation only on path arguments. Do not inspect arbitrary free-form code/text.
- Lazy-load providers. Registry entries can be tiny loader functions or import-on-demand wrappers; the harness should only import the provider the user actually selected.

## Test Evidence

- `pytest tests/unit/test_permissions.py tests/unit/test_routing.py tests/unit/test_hooks.py -q`
  - Result: `64 passed in 0.19s`
- `pytest tests/unit/test_cli.py -q`
  - Result: `24 passed in 9.21s`

## Proposed Fixes

### 1. Permissions Flow

#### What I would change

I would make permissions explicit and honest by introducing a small approval result type instead of treating approvals as a boolean.

Files:
- `agent_harness/permissions.py`
- `agent_harness/cli.py`
- tests for permissions and CLI flow

Core change:
- Replace the current `PromptFn = Callable[[ToolCall], bool]` with something that can return a real decision:
  - `deny`
  - `allow_once`
  - `allow_session`
  - `allow_persistent`
- Wire persistence properly:
  - CLI passes a workspace-local persistence path to `Permissions`
  - CLI calls `permissions.load()` at startup
  - CLI calls `permissions.save()` before exit if anything persistent changed
- Make the UI match the implementation. If persistent approval is supported, show it in the prompt. If not, remove it from the product claims.

Pseudo-code:

```python
class ApprovalMode(Enum):
    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_PERSISTENT = "allow_persistent"


class PermissionDecision(NamedTuple):
    approved: bool
    mode: ApprovalMode


def prompt(tool_call: ToolCall) -> PermissionDecision:
    choice = input("[o]nce / [s]ession / [p]ersistent / [d]eny")
    mapping = {
        "o": PermissionDecision(True, ApprovalMode.ALLOW_ONCE),
        "s": PermissionDecision(True, ApprovalMode.ALLOW_SESSION),
        "p": PermissionDecision(True, ApprovalMode.ALLOW_PERSISTENT),
        "d": PermissionDecision(False, ApprovalMode.DENY),
    }
    return mapping[choice]
```

```python
def check(self, tool_call: ToolCall) -> bool:
    if tool_call.name in self._persistent_approved:
        return True
    if tool_call.name in self._session_approved:
        return True

    decision = self._prompt_fn(tool_call)
    if not decision.approved:
        return False
    if decision.mode is ApprovalMode.ALLOW_SESSION:
        self._session_approved.add(tool_call.name)
    if decision.mode is ApprovalMode.ALLOW_PERSISTENT:
        self._persistent_approved.add(tool_call.name)
        self._dirty = True
    return True
```

#### Why this approach

It keeps the system small while making it truthful. The main problem is not lack of code, it is that the current code hides distinct behaviors behind `True` and `False`. That is exactly the kind of shortcut that makes later behavior confusing.

#### Options considered

Option selected: explicit decision enum / result object.
- Best fit for clarity.
- Keeps the policy in one place.
- Easy to test.

Option rejected: encode the choice in a string and branch on string literals everywhere.
- Slightly less code up front.
- Worse readability and easier to break.

Option rejected: remove session/persistent approvals entirely.
- Simpler, but it would back away from a useful feature the docs already promise.
- I would only choose this if you decide the harness should aggressively shrink scope.

### 2. Sub-Agent Runtime Consistency

#### What I would change

I would stop having two separate ways to run an agent. Right now CLI execution and `run_agent()` execution are parallel code paths with different behavior. I would introduce one small internal runtime entry point that both use.

Files:
- `agent_harness/cli.py`
- `agent_harness/routing.py`
- possibly a new small file such as `agent_harness/runtime.py`

Core change:
- Extract the common setup from `cli.run_agent()` into a reusable function:
  - load config
  - apply overrides if any
  - build full system prompt
  - configure tools/runtime state
  - create hooks, permissions, tracer, budget, callbacks
  - run selected loop
- `routing.run_agent()` should call that same runtime function with:
  - `prompt=message`
  - non-interactive permissions policy
  - optional tracing disabled or minimal

Pseudo-code:

```python
@dataclass
class AgentRunRequest:
    agent_dir: str
    prompt: str | None
    messages: list[Message] | None = None
    interactive: bool = False
    session_path: str | None = None


def execute_agent(request: AgentRunRequest) -> str:
    config = load_config(request.agent_dir)
    runtime = build_runtime(config, interactive=request.interactive)
    messages = request.messages or [Message("system", build_system_prompt(config))]
    if request.prompt:
        messages.append(Message("user", request.prompt))
    return runtime.loop(runtime.chat_fn, messages, runtime.tool_schemas, config, runtime.callbacks)
```

```python
def run_agent(agent_name: str, message: str) -> str:
    return execute_agent(
        AgentRunRequest(
            agent_dir=f"{agents_dir}/{agent_name}",
            prompt=message,
            interactive=False,
        )
    )
```

#### Why this approach

The harness claims an agent folder is the unit of portability. That only stays true if every execution path loads the same prompt context and applies the same deterministic runtime rules. One runtime path is simpler than two almost-the-same paths.

#### Options considered

Option selected: extract a shared runtime function.
- Best trade-off between simplicity and correctness.
- Preserves current structure without a large rewrite.

Option rejected: duplicate the CLI setup inside `routing.py`.
- Fastest short-term patch.
- Makes drift worse and guarantees future inconsistency.

Option rejected: make sub-agents shell out to `python -m agent_harness run ...`.
- Attractive because it reuses the CLI literally.
- Rejected because it is heavier, slower, harder to test, and adds subprocess coupling where a direct call is enough.

### 3. Remove Module-Global Runtime State

#### What I would change

I would remove mutable module-level execution settings such as:
- `memory.memory_dir`
- `tools.tool_timeout`
- `tools.active_executor`
- routing depth globals where practical

Instead I would pass a small runtime context object into tool execution.

Files:
- `agent_harness/tools.py`
- `agent_harness/memory.py`
- `agent_harness/cli.py`
- `agent_harness/routing.py`
- maybe `agent_harness/types.py` or a new `agent_harness/runtime.py`

Core change:
- Define a tiny immutable context carrying per-run settings.
- Built-in tools become closures or methods bound to that context when the run starts.
- Tool registry for built-ins is created per run, not as a single mutable global.

Pseudo-code:

```python
@dataclass(frozen=True)
class RuntimeContext:
    agent_dir: str
    memory_dir: str
    tool_timeout: int
    executor: str
```

```python
def make_builtin_tools(ctx: RuntimeContext) -> dict[str, Callable[..., str]]:
    def read_file(path: str) -> str:
        return Path(path).read_text()

    def save_memory(key: str, content: str) -> str:
        target = Path(ctx.memory_dir) / f"{key}.md"
        ...

    def execute_code(code: str, language: str = "python") -> str:
        return executor_registry[ctx.executor](code, language, ctx.tool_timeout)

    return {
        "read_file": read_file,
        "save_memory": save_memory,
        "execute_code": execute_code,
    }
```

#### Why this approach

Global mutable settings are the main source of hidden complexity in the repo. They make nested agent execution unpredictable and make the code look simpler than it is. A small context object is the minimum structure needed to make runtime behavior explicit.

#### Options considered

Option selected: immutable runtime context passed at setup time.
- Small and explicit.
- Fixes the actual coupling problem.
- Makes tests easier because each run can build its own isolated tool set.

Option rejected: keep globals but "carefully reset them" before and after each run.
- Superficially smaller patch.
- Fragile, especially with nested calls and future concurrency.

Option rejected: convert everything into classes with deep dependency injection.
- Solves the problem technically.
- Too much structure for the repo’s stated goal.

### 4. Path Traversal Validation

#### What I would change

I would narrow the hook so it validates only arguments that are meant to be paths, and validate them as paths rather than raw substrings.

Files:
- `agent_harness/hooks.py`
- possibly `agent_harness/tools.py` if tool schemas need path metadata

Core change:
- Only inspect path-like argument names such as `path`, `file_path`, `working_dir`.
- Resolve candidate paths against an allowed base directory.
- Block only if the resolved path escapes the base directory.

Pseudo-code:

```python
PATH_ARG_NAMES = {"path", "working_dir", "file_path"}


def _is_safe_path(raw: str, base_dir: Path) -> bool:
    target = (base_dir / raw).resolve()
    return target.is_relative_to(base_dir.resolve())


def path_traversal_detector(tool_call: ToolCall) -> ToolCall | None:
    for name, value in tool_call.arguments.items():
        if name not in PATH_ARG_NAMES:
            continue
        if isinstance(value, str) and not _is_safe_path(value, workspace_root):
            return None
    return tool_call
```

#### Why this approach

The current check is trying to be simple, but it is the wrong simplicity: cheap to write, expensive in false positives. Path validation should operate on path arguments only. That is both simpler in behavior and easier to explain.

#### Options considered

Option selected: name-based path validation with real path resolution.
- Good enough for this repo.
- Avoids scanning arbitrary code and prose.

Option rejected: inspect every string argument for suspicious substrings.
- This is the current approach.
- It is noisy and semantically wrong.

Option rejected: introduce a full security policy engine per tool schema.
- More precise in theory.
- Far too heavy for this project.

### 5. Provider Loading

#### What I would change

I would lazy-load providers so the composition root does not import optional SDKs unless the chosen provider needs them.

Files:
- `agent_harness/providers/__init__.py`
- any validation code that currently assumes a pre-imported registry

Core change:
- Registry maps provider names to loader functions or import paths, not direct function objects.
- `get_provider("anthropic")` imports the module on demand and returns `chat`.

Pseudo-code:

```python
PROVIDERS = {
    "anthropic": "agent_harness.providers.anthropic",
    "openai": "agent_harness.providers.openai_provider",
}


def get_provider(name: str) -> ChatFn:
    module_name = PROVIDERS[name]
    module = importlib.import_module(module_name)
    return module.chat
```

```python
def validate_config(config: AgentConfig) -> None:
    if config.provider not in PROVIDERS:
        raise ValueError(...)
```

#### Why this approach

It preserves the flat registry idea but removes unnecessary coupling from the CLI import path. This is a small structural improvement with very little conceptual cost.

#### Options considered

Option selected: import-on-demand provider lookup.
- Minimal change.
- Keeps provider files standalone.

Option rejected: keep eager imports because "the venv has both packages anyway".
- Works today, but it is still the wrong dependency direction.
- Makes the CLI less modular than it claims to be.

Option rejected: create a provider plugin framework.
- Overkill.
- Adds abstraction the project does not need.
