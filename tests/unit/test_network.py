"""Tests for agent_harness.network."""

import threading
import time

from agent_harness.network import make_network_blocker
from agent_harness.types import ToolCall


def _fetch(url: str) -> ToolCall:
    return ToolCall(id="tc", name="web_fetch", arguments={"url": url})


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
