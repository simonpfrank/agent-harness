"""Integration tests for all loop patterns with REAL LLM calls.

No mocks. Every test calls a real Anthropic API endpoint.
Skipped if ANTHROPIC_API_KEY is not set.
"""

import os

import pytest
from dotenv import load_dotenv

from agent_harness.config import load
from agent_harness.loops import registry as loop_registry
from agent_harness.providers import registry as provider_registry
from agent_harness.tools import execute_tool, generate_schema
from agent_harness.tools import registry as tool_registry
from agent_harness.types import LoopCallbacks, Message

load_dotenv()

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


def _run_agent(agent_dir: str, prompt: str) -> str:
    """Run an agent end-to-end and return the final response."""
    cfg = load(agent_dir)
    chat_fn = provider_registry[cfg.provider]
    loop_fn = loop_registry[cfg.loop]
    schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]
    cb = LoopCallbacks(on_tool_call=execute_tool)
    messages = [
        Message(role="system", content=cfg.instructions),
        Message(role="user", content=prompt),
    ]
    return loop_fn(chat_fn, messages, schemas, cfg, cb)


@requires_api_key
class TestReactLoop:
    def test_simple_question(self) -> None:
        result = _run_agent("tests/data/agent_react", "What is 2+2? Reply with just the number.")
        assert "4" in result

    def test_tool_use(self) -> None:
        result = _run_agent(
            "tests/data/agent_react",
            "Read tests/data/agent_react/instructions.md and quote the first word.",
        )
        assert "You" in result or "test" in result.lower()


@requires_api_key
class TestReflectionLoop:
    def test_generates_and_critiques(self) -> None:
        result = _run_agent("tests/data/agent_reflection", "What is 2+2? Reply with the number.")
        assert "4" in result

    def test_with_tool_use(self) -> None:
        result = _run_agent(
            "tests/data/agent_reflection",
            "Read tests/data/agent_reflection/config.yaml and tell me the model name.",
        )
        assert "haiku" in result.lower() or "claude" in result.lower()


@requires_api_key
class TestEvalOptimizeLoop:
    def test_generates_and_scores(self) -> None:
        result = _run_agent(
            "tests/data/agent_eval_optimize",
            "Read tests/data/agent_eval_optimize/config.yaml and list every field.",
        )
        assert "name" in result.lower()

    def test_with_tool_use(self) -> None:
        result = _run_agent(
            "tests/data/agent_eval_optimize",
            "How many lines in tests/data/agent_eval_optimize/instructions.md?",
        )
        assert result  # Got some response without crashing


@requires_api_key
class TestReWOOLoop:
    def test_plan_and_solve(self) -> None:
        result = _run_agent("tests/data/agent_rewoo", "What is 2+2? Reply with just the number.")
        assert "4" in result


@requires_api_key
class TestRalphLoop:
    def test_succeeds_with_done(self) -> None:
        result = _run_agent("tests/data/agent_ralph", "Say hello and then say DONE.")
        assert "DONE" in result or "done" in result.lower()


@requires_api_key
class TestDebateLoop:
    def test_produces_synthesis(self) -> None:
        result = _run_agent("tests/data/agent_debate", "Is Python a good first programming language?")
        assert len(result) > 20  # Non-trivial synthesis


@requires_api_key
class TestPlanExecuteLoop:
    def test_plans_and_executes(self) -> None:
        result = _run_agent(
            "tests/data/agent_plan_execute",
            "List the files in tests/data/agent_plan_execute/ and count them.",
        )
        assert result  # Got some response without crashing
