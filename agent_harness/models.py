"""Single source of truth for per-model cost, context, and behavior metadata.

Replaces what used to be three separately-maintained tables
(`budget.py::COST_TABLE`, `context.py::_CONTEXT_LIMITS`,
`openai_provider.py::_SUPPORTED_RESPONSE_MODELS`) that could silently drift
out of sync with each other. One entry per model, both cost and context
together — it's structurally impossible to add a cost-only or
context-only entry here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """Per-model cost, context, and behavior metadata.

    Attributes:
        input_cost_per_million: USD cost per 1M input tokens.
        output_cost_per_million: USD cost per 1M output tokens.
        context_limit: Context window size in tokens.
        minimal_reasoning_default: OpenAI-only. If True and no explicit
            `reasoning_effort` is set, defaults to minimal reasoning effort.
    """

    input_cost_per_million: float
    output_cost_per_million: float
    context_limit: int
    minimal_reasoning_default: bool = False


MODEL_REGISTRY: dict[tuple[str, str], ModelSpec] = {
    ("anthropic", "claude-haiku-4-5-20251001"): ModelSpec(1.00, 5.00, 200_000),
    ("anthropic", "claude-sonnet-4-6"): ModelSpec(3.00, 15.00, 200_000),
    # Introductory pricing through Aug 31, 2026
    ("anthropic", "claude-sonnet-5"): ModelSpec(2.00, 10.00, 1_000_000),
    ("anthropic", "claude-opus-4-6"): ModelSpec(15.00, 75.00, 200_000),  # Legacy model
    ("anthropic", "claude-opus-4-8"): ModelSpec(5.00, 25.00, 1_000_000),  # Earlier opus model
    ("anthropic", "claude-opus-5"): ModelSpec(5.00, 25.00, 1_000_000),
    ("anthropic", "claude-fable-5"): ModelSpec(10.00, 50.00, 1_000_000),
    ("openai", "gpt-4o-mini"): ModelSpec(0.15, 0.60, 128_000),
    ("openai", "gpt-4o"): ModelSpec(2.50, 10.00, 128_000),
    ("openai", "gpt-5.4"): ModelSpec(2.50, 15.00, 1_000_000),
    ("openai", "gpt-5.4-mini"): ModelSpec(0.75, 4.50, 400_000),
    ("openai", "gpt-5.4-nano"): ModelSpec(0.20, 1.25, 400_000),
    ("openai", "gpt-5.1"): ModelSpec(1.25, 10.00, 400_000),
    ("openai", "gpt-5-mini"): ModelSpec(0.25, 2.00, 400_000, minimal_reasoning_default=True),
    ("openai", "gpt-5-nano"): ModelSpec(0.05, 0.40, 400_000, minimal_reasoning_default=True),
    ("openai", "gpt-5"): ModelSpec(1.25, 10.00, 128_000, minimal_reasoning_default=True),  # context: unconfirmed
    ("openai", "gpt-5-pro"): ModelSpec(15.00, 120.00, 128_000),  # context: unconfirmed
    ("openai", "gpt-5.5"): ModelSpec(5.00, 30.00, 128_000),  # context: unconfirmed
    ("openai", "gpt-5.5-pro"): ModelSpec(30.00, 180.00, 128_000),  # context: unconfirmed
    ("openai", "gpt-5.6-luna"): ModelSpec(0.20, 1.20, 400_000),
    ("openai", "gpt-5.6-terra"): ModelSpec(2.00, 12.00, 128_000),  # context: unconfirmed
    ("openai", "gpt-5.6-sol"): ModelSpec(5.00, 30.00, 128_000),  # context: unconfirmed
    # o1/o3/o4 (o-series reasoning models) are deliberately excluded — not
    # supported by this provider. See openai_provider.py::_EXCLUDED_MODEL_PREFIXES.
}
