"""Budget tracking for turns and cost."""

from __future__ import annotations

from agent_harness.types import AgentConfig, Usage

# Cost per million tokens: (input, output)
COST_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-haiku-4-5-20251001"): (0.80, 4.00),
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-opus-4-6"): (15.00, 75.00),
}


class Budget:
    """Tracks turn count and estimated cost against configured limits.

    Args:
        config: Agent configuration with optional max_turns and max_cost.
    """

    def __init__(self, config: AgentConfig) -> None:
        self._max_turns = config.max_turns
        self._max_cost = config.max_cost
        self._provider = config.provider
        self._model = config.model
        self._turns = 0
        self._total_cost = 0.0

    def record(self, usage: Usage) -> bool:
        """Record usage from one LLM call. Returns True if budget exceeded.

        Args:
            usage: Token counts from the LLM response.

        Returns:
            True if any budget limit has been exceeded.
        """
        self._turns += 1
        rates = COST_TABLE.get((self._provider, self._model), (0.0, 0.0))
        input_cost = (usage.input_tokens / 1_000_000) * rates[0]
        output_cost = (usage.output_tokens / 1_000_000) * rates[1]
        self._total_cost += input_cost + output_cost

        if self._turns >= self._max_turns:
            return True
        return self._max_cost is not None and self._total_cost >= self._max_cost

    def summary(self) -> str:
        """Human-readable budget status.

        Returns:
            Status string with turn count and cost.
        """
        parts = [f"Turn {self._turns}/{self._max_turns}"]
        cost_str = f"${self._total_cost:.4f}"
        if self._max_cost is not None:
            cost_str += f"/${self._max_cost:.2f}"
        parts.append(cost_str)
        return " | ".join(parts)
