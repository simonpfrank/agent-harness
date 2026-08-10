"""Tests for agent_harness.models."""

from agent_harness.models import MODEL_REGISTRY, ModelSpec


class TestModelSpec:
    def test_construction(self) -> None:
        spec = ModelSpec(1.0, 2.0, 100_000)
        assert spec.input_cost_per_million == 1.0
        assert spec.output_cost_per_million == 2.0
        assert spec.context_limit == 100_000
        assert spec.minimal_reasoning_default is False

    def test_minimal_reasoning_default_override(self) -> None:
        spec = ModelSpec(1.0, 2.0, 100_000, minimal_reasoning_default=True)
        assert spec.minimal_reasoning_default is True


class TestModelRegistryInvariants:
    def test_not_empty(self) -> None:
        assert len(MODEL_REGISTRY) > 0

    def test_every_entry_has_positive_cost(self) -> None:
        for key, spec in MODEL_REGISTRY.items():
            assert spec.input_cost_per_million > 0, key
            assert spec.output_cost_per_million > 0, key

    def test_every_entry_has_positive_context_limit(self) -> None:
        for key, spec in MODEL_REGISTRY.items():
            assert spec.context_limit > 0, key

    def test_no_o_series_models_registered(self) -> None:
        for provider, model in MODEL_REGISTRY:
            if provider == "openai":
                assert not model.startswith(("o1", "o3", "o4")), model

    def test_keys_are_provider_model_tuples(self) -> None:
        for provider, model in MODEL_REGISTRY:
            assert provider in ("anthropic", "openai")
            assert isinstance(model, str) and model
