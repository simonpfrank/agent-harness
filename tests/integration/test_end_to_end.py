"""Integration tests — real config, real tools, real API calls.

Tests requiring ANTHROPIC_API_KEY are skipped if the key is not set.
"""

import os

import pytest
from dotenv import load_dotenv

from agent_harness.budget import Budget
from agent_harness.config import load
from agent_harness.loops.react import run
from agent_harness.providers import registry as provider_registry
from agent_harness.tools import execute_tool, generate_schema
from agent_harness.tools import registry as tool_registry
from agent_harness.types import LoopCallbacks, Message, Usage

load_dotenv()

requires_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


class TestConfigAndToolsIntegration:
    def test_load_hello_agent(self) -> None:
        cfg = load("agents/hello")
        assert cfg.name == "hello"
        assert cfg.provider == "anthropic"
        assert set(cfg.tools) == {"run_command", "read_file", "execute_code"}

    def test_generate_schemas_for_configured_tools(self) -> None:
        cfg = load("agents/hello")
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]
        assert len(schemas) == 3
        names = {s["name"] for s in schemas}
        assert names == {"run_command", "read_file", "execute_code"}

    def test_tool_execution_read_file(self) -> None:
        from agent_harness.types import ToolCall

        tc = ToolCall(id="tc_1", name="read_file",
                      arguments={"path": "agents/hello/instructions.md"})
        result = execute_tool(tc)
        assert result.error is None
        assert "helpful assistant" in (result.output or "")

    def test_tool_error_returned_not_crashed(self) -> None:
        from agent_harness.types import ToolCall

        tc = ToolCall(id="tc_2", name="read_file",
                      arguments={"path": "/nonexistent/path.txt"})
        result = execute_tool(tc)
        assert result.error is not None
        assert result.output is None


class TestProviderKwargsPassthrough:
    @requires_anthropic_key
    def test_anthropic_accepts_temperature(self) -> None:
        """Passing temperature=0.0 to Anthropic must not raise."""
        from agent_harness.providers.anthropic import chat

        result = chat(
            [Message(role="user", content="Reply with just the word ok.")],
            tools=[],
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
            max_tokens=50,
        )
        assert result.message.content is not None

    @requires_openai_key
    def test_openai_accepts_temperature_and_max_tokens(self) -> None:
        """Passing temperature=0.0 and max_tokens to OpenAI must not raise."""
        from agent_harness.providers.openai_provider import chat

        result = chat(
            [Message(role="user", content="Reply with just the word ok.")],
            tools=[],
            model="gpt-4o-mini",
            temperature=0.0,
            max_tokens=50,
        )
        assert result.message.content is not None


class TestInvalidConfig:
    def test_missing_instructions_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("tests/data/invalid_agent_no_instructions")

    def test_bad_provider_raises(self) -> None:
        from agent_harness.cli import validate_config

        cfg = load("tests/data/invalid_agent_bad_provider")
        with pytest.raises(ValueError, match="provider"):
            validate_config(cfg)


@requires_anthropic_key
class TestRealLLMIntegration:
    def test_single_turn_simple_question(self) -> None:
        """LLM answers a simple question without tool use."""
        cfg = load("agents/hello")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="What is 2 + 2? Reply with just the number."),
        ]
        result = run(chat_fn, messages, schemas, cfg)
        assert "4" in result

    def test_tool_use_list_files(self) -> None:
        """LLM uses run_command to list files."""
        cfg = load("agents/hello")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="List the files in the agents/hello directory."),
        ]
        cb = LoopCallbacks(on_tool_call=execute_tool)
        result = run(chat_fn, messages, schemas, cfg, callbacks=cb)
        assert "config.yaml" in result or "instructions.md" in result

    def test_tool_use_read_file(self) -> None:
        """LLM uses read_file to read a file and report contents."""
        cfg = load("agents/hello")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="Read agents/hello/config.yaml and tell me the model name."),
        ]
        cb = LoopCallbacks(on_tool_call=execute_tool)
        result = run(chat_fn, messages, schemas, cfg, callbacks=cb)
        assert "haiku" in result.lower() or "claude" in result.lower()

    def test_budget_tracking_real(self) -> None:
        """Budget tracks real token usage."""
        cfg = load("agents/hello")
        chat_fn = provider_registry[cfg.provider]
        budget = Budget(cfg)

        def on_budget(usage: Usage) -> bool:
            return budget.record(usage)

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="Say hello in one word."),
        ]
        cb = LoopCallbacks(on_budget=on_budget)
        run(chat_fn, messages, [], cfg, callbacks=cb)
        summary = budget.summary()
        assert "1" in summary
        assert "$" in summary


@requires_openai_key
class TestOpenAIIntegration:
    def test_single_turn_simple_question(self) -> None:
        """OpenAI answers a simple question without tool use."""
        cfg = load("tests/data/agent_openai")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="What is 2 + 2? Reply with just the number."),
        ]
        result = run(chat_fn, messages, schemas, cfg)
        assert "4" in result

    def test_tool_use_list_files(self) -> None:
        """OpenAI uses run_command to list files."""
        cfg = load("tests/data/agent_openai")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="List the files in the tests/data/agent_openai directory."),
        ]
        cb = LoopCallbacks(on_tool_call=execute_tool)
        result = run(chat_fn, messages, schemas, cfg, callbacks=cb)
        assert "config.yaml" in result or "instructions.md" in result

    def test_tool_use_read_file(self) -> None:
        """OpenAI uses read_file and reports contents."""
        cfg = load("tests/data/agent_openai")
        chat_fn = provider_registry[cfg.provider]
        schemas = [generate_schema(tool_registry[t]) for t in cfg.tools]

        messages = [
            Message(role="system", content=cfg.instructions),
            Message(role="user", content="Read tests/data/agent_openai/config.yaml and tell me the provider name."),
        ]
        cb = LoopCallbacks(on_tool_call=execute_tool)
        result = run(chat_fn, messages, schemas, cfg, callbacks=cb)
        assert "openai" in result.lower()
