"""Budget tracking for turns and cost."""

from __future__ import annotations

from agent_harness.models import MODEL_REGISTRY
from agent_harness.types import AgentConfig, Usage


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
        spec = MODEL_REGISTRY.get((self._provider, self._model))
        input_rate = spec.input_cost_per_million if spec else 0.0
        output_rate = spec.output_cost_per_million if spec else 0.0
        input_cost = (usage.input_tokens / 1_000_000) * input_rate
        output_cost = (usage.output_tokens / 1_000_000) * output_rate
        self._total_cost += input_cost + output_cost

        if self._turns >= self._max_turns:
            return True
        return self._max_cost is not None and self._total_cost >= self._max_cost

    @property
    def turns(self) -> int:
        """Turns recorded so far."""
        return self._turns

    @property
    def total_cost(self) -> float:
        """Estimated USD cost accumulated so far."""
        return self._total_cost

    def status_note(self) -> str:
        """Human-readable remaining-budget note for injection into a turn.

        Returns:
            A note stating turns remaining, and estimated cost remaining
            if `max_cost` is configured.
        """
        remaining_turns = max(self._max_turns - self._turns, 0)
        note = f"You have {remaining_turns} turn(s) remaining."
        if self._max_cost is not None:
            remaining_cost = max(self._max_cost - self._total_cost, 0.0)
            note += f" Estimated ${remaining_cost:.4f} remaining."
        return note

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
