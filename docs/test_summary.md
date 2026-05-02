# Test Summary

## Unit Tests

Last verified in `.venv` with:
- `.venv/bin/pytest tests/unit -q`
- Result: `305 passed in 1.65s`

Key coverage areas:
- Runtime prep and shared execution path
- CLI argument parsing and run flow
- Tool registry building, execution, truncation, and discovery
- Permissions with explicit once/session/persistent approvals
- Hooks including path-aware traversal blocking and network allowlists
- Routing depth protection and delegated run behavior
- Provider adapters and retry helpers, including OpenAI Responses routing, GPT-5 compatibility, and Chat Completions fallback for custom `base_url`
- Memory helpers, sessions, tracing, logging, config loading, and loop patterns

## Integration Tests

Last verified on the host with the repo virtualenv:
- `.venv/bin/pytest tests/integration -q`
- Result: `60 passed in 66.98s (0:01:06)`

Covered scenarios:
- Dangerous commands blocked before execution
- Path traversal blocked for path-like args but not arbitrary free-form text/code
- Network exfiltration blocked by default
- Secrets redacted and injection output wrapped
- Custom tools discovered and executed from `tools/`
- Shared and agent-local skills loaded into prompt context
- Config loading, schema generation, and local tool execution
- Invalid config/provider handling
- Live Anthropic and OpenAI provider flows
- Live GPT-5-family provider smoke tests through the OpenAI provider
- End-to-end CLI and real feature behavior
