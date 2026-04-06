"""Tests for agent_harness.permissions."""

import os
import tempfile

from agent_harness.permissions import Permissions
from agent_harness.types import ToolCall


def _tool_call(name: str) -> ToolCall:
    return ToolCall(id="tc_1", name=name, arguments={})


class TestDefaultPermissions:
    def test_no_config_allows_everything(self) -> None:
        perms = Permissions({}, prompt_fn=lambda tc: False)
        assert perms.check(_tool_call("run_command")) is True

    def test_no_config_never_prompts(self) -> None:
        called = False

        def should_not_call(tc: ToolCall) -> bool:
            nonlocal called
            called = True
            return True

        perms = Permissions({}, prompt_fn=should_not_call)
        perms.check(_tool_call("run_command"))
        assert called is False


class TestAlwaysAllow:
    def test_allowed_tools_pass_without_prompt(self) -> None:
        called = False

        def should_not_call(tc: ToolCall) -> bool:
            nonlocal called
            called = True
            return True

        perms = Permissions({"always_allow": ["read_file"]}, prompt_fn=should_not_call)
        assert perms.check(_tool_call("read_file")) is True
        assert called is False


class TestAlwaysAsk:
    def test_denied_when_user_says_no(self) -> None:
        perms = Permissions({"always_ask": ["run_command"]}, prompt_fn=lambda tc: False)
        assert perms.check(_tool_call("run_command")) is False

    def test_allowed_when_user_says_yes(self) -> None:
        perms = Permissions({"always_ask": ["run_command"]}, prompt_fn=lambda tc: True)
        assert perms.check(_tool_call("run_command")) is True

    def test_always_ask_prompts_every_time(self) -> None:
        call_count = 0

        def counting_prompt(tc: ToolCall) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        perms = Permissions({"always_ask": ["run_command"]}, prompt_fn=counting_prompt)
        perms.check(_tool_call("run_command"))
        perms.check(_tool_call("run_command"))
        assert call_count == 2


class TestSessionMemory:
    def test_approved_tool_not_asked_again(self) -> None:
        """When config exists but tool is in neither list, ask once per session."""
        call_count = 0

        def counting_prompt(tc: ToolCall) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        # Config has lists but execute_code is in neither → default tier
        perms = Permissions(
            {"always_allow": ["read_file"], "always_ask": ["run_command"]},
            prompt_fn=counting_prompt,
        )
        perms.check(_tool_call("execute_code"))  # first call → prompted
        perms.check(_tool_call("execute_code"))  # second → session memory
        assert call_count == 1

    def test_denied_tool_asked_again(self) -> None:
        """Denied tools are not remembered — ask each time."""
        call_count = 0

        def counting_deny(tc: ToolCall) -> bool:
            nonlocal call_count
            call_count += 1
            return False

        perms = Permissions(
            {"always_allow": ["read_file"]},
            prompt_fn=counting_deny,
        )
        perms.check(_tool_call("execute_code"))
        perms.check(_tool_call("execute_code"))
        assert call_count == 2


class TestPersistentPermissions:
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, ".permissions.yaml")
            perms = Permissions({}, prompt_fn=lambda tc: True, persist_path=path)
            perms.check(_tool_call("run_command"))  # approve and persist
            perms.save()

            # New instance loads persisted permissions
            perms2 = Permissions({}, prompt_fn=lambda tc: False, persist_path=path)
            perms2.load()
            assert perms2.check(_tool_call("run_command")) is True  # loaded, no prompt
