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
        assert budget.record(usage) is True  # turn 3 — hit limit


class TestBudgetCostTracking:
    def test_tracks_cost(self) -> None:
        budget = Budget(_config(max_cost=0.001))
        # Haiku pricing (MODEL_REGISTRY): $1.00/M input, $5.00/M output
        # 1000 input tokens = $0.001, 1000 output = $0.005 → total $0.006
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


class TestBudgetRawProperties:
    def test_turns_and_total_cost_start_at_zero(self) -> None:
        budget = Budget(_config())
        assert budget.turns == 0
        assert budget.total_cost == 0.0

    def test_turns_and_total_cost_after_recording(self) -> None:
        budget = Budget(_config(max_turns=10))
        budget.record(Usage(input_tokens=1000, output_tokens=1000))
        budget.record(Usage(input_tokens=1000, output_tokens=1000))
        assert budget.turns == 2
        assert budget.total_cost > 0.0


class TestBudgetStatusNote:
    def test_turns_only_when_no_max_cost(self) -> None:
        budget = Budget(_config(max_turns=5, max_cost=None))
        note = budget.status_note()
        assert note == "You have 5 turn(s) remaining."

    def test_includes_cost_when_max_cost_set(self) -> None:
        budget = Budget(_config(max_turns=5, max_cost=0.50))
        note = budget.status_note()
        assert "5 turn(s) remaining" in note
        assert "$0.5000 remaining" in note

    def test_reflects_consumed_turns(self) -> None:
        budget = Budget(_config(max_turns=5, max_cost=None))
        budget.record(Usage(input_tokens=10, output_tokens=10))
        note = budget.status_note()
        assert "4 turn(s) remaining" in note

    def test_reflects_consumed_cost(self) -> None:
        budget = Budget(_config(max_turns=10, max_cost=0.01))
        budget.record(Usage(input_tokens=1000, output_tokens=1000))
        note = budget.status_note()
        assert "$" in note

    def test_remaining_turns_never_negative(self) -> None:
        budget = Budget(_config(max_turns=1, max_cost=None))
        budget.record(Usage(input_tokens=10, output_tokens=10))
        budget.record(Usage(input_tokens=10, output_tokens=10))
        note = budget.status_note()
        assert "0 turn(s) remaining" in note

    def test_remaining_cost_never_negative(self) -> None:
        budget = Budget(_config(max_turns=10, max_cost=0.0001))
        budget.record(Usage(input_tokens=10_000, output_tokens=10_000))
        note = budget.status_note()
        assert "$0.0000 remaining" in note
