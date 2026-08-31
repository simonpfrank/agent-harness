"""Tests for agent_harness.network."""

import threading
import time

from agent_harness.network import _has_network_intent, make_network_blocker
from agent_harness.types import ToolCall


def _fetch(url: str) -> ToolCall:
    return ToolCall(id="tc", name="web_fetch", arguments={"url": url})


class TestHasNetworkIntent:
    """Per-tool-name dispatch in _has_network_intent — no test existed for
    this directly before (only the end-to-end make_network_blocker test
    below), so covering the existing branches alongside the new one."""

    def test_web_fetch_returns_its_url(self) -> None:
        call = ToolCall(id="tc", name="web_fetch", arguments={"url": "https://example.com/x"})
        assert _has_network_intent(call) == (True, "https://example.com/x")

    def test_run_command_without_network_pattern_is_not_network(self) -> None:
        call = ToolCall(id="tc", name="run_command", arguments={"command": "ls -la"})
        assert _has_network_intent(call) == (False, "")

    def test_unknown_tool_is_not_network(self) -> None:
        call = ToolCall(id="tc", name="read_file", arguments={"path": "x.txt"})
        assert _has_network_intent(call) == (False, "")

    def test_browser_navigate_returns_its_url(self) -> None:
        call = ToolCall(id="tc", name="browser_navigate", arguments={"url": "https://bbc.co.uk/news"})
        assert _has_network_intent(call) == (True, "https://bbc.co.uk/news")

    def test_browser_navigate_missing_url_returns_empty_string(self) -> None:
        call = ToolCall(id="tc", name="browser_navigate", arguments={})
        assert _has_network_intent(call) == (True, "")


class TestConcurrentDomainPrompting:
    """Parallel tool-call execution means two calls to different new domains
    can now fire from different threads in the same turn — previously
    impossible. An unserialized prompt_fn would race on stdin/stdout."""

    def test_prompts_never_overlap(self) -> None:
        in_flight = 0
        max_concurrent = 0
        lock = threading.Lock()

        def slow_prompt(domain: str) -> bool:
            nonlocal in_flight, max_concurrent
            with lock:
                in_flight += 1
                max_concurrent = max(max_concurrent, in_flight)
            time.sleep(0.05)  # widen the race window
            with lock:
                in_flight -= 1
            return True

        blocker = make_network_blocker(allowed_domains=set(), prompt_fn=slow_prompt)
        threads = [
            threading.Thread(target=blocker, args=(_fetch(f"https://site-{i}.example.com/x"),))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent == 1
