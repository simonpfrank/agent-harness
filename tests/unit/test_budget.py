"""Tests for agent_harness.budget."""

from agent_harness.budget import Budget
from agent_harness.types import AgentConfig, Usage


def _config(max_turns: int = 10, max_cost: float | None = None) -> AgentConfig:
    return AgentConfig(
        name="test",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test",
        instructions="test",
        max_turns=max_turns,
        max_cost=max_cost,
    )


class TestBudgetNoLimits:
    def test_never_exceeded(self) -> None:
        budget = Budget(_config(max_turns=999, max_cost=None))
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert budget.record(usage) is False


class TestBudgetTurnTracking:
    def test_tracks_turns(self) -> None:
        budget = Budget(_config(max_turns=3))
        usage = Usage(input_tokens=10, output_tokens=10)
        assert budget.record(usage) is False  # turn 1
        assert budget.record(usage) is False  # turn 2
        assert budget.record(usage) is True   # turn 3 — hit limit


class TestBudgetCostTracking:
    def test_tracks_cost(self) -> None:
        budget = Budget(_config(max_cost=0.001))
        # Haiku pricing: $0.80/M input, $4.00/M output
        # 1000 input tokens = $0.0008, 1000 output = $0.004 → total $0.0048
        usage = Usage(input_tokens=1000, output_tokens=1000)
        assert budget.record(usage) is True  # exceeds $0.001

    def test_accumulates(self) -> None:
        budget = Budget(_config(max_cost=0.01))
        small = Usage(input_tokens=100, output_tokens=100)
        assert budget.record(small) is False
        assert budget.record(small) is False
        # Should still be under $0.01 after 2 small calls


class TestBudgetSummary:
    def test_summary_string(self) -> None:
        budget = Budget(_config(max_turns=10, max_cost=0.50))
        budget.record(Usage(input_tokens=100, output_tokens=50))
        summary = budget.summary()
        assert "1" in summary  # turn count
        assert "$" in summary  # cost
