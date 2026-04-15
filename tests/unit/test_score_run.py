"""Tests for scripts.score_run."""

from scripts.score_run import score


def _expected() -> dict:
    return {
        "matches": [
            {"input": "Sex", "reference": "Primary Gender"},
            {"input": "State", "reference": "State"},
            {"input": "UniqueID", "reference": "Record ID"},
        ]
    }


class TestScore:
    def test_all_correct(self) -> None:
        output = {
            "matches": [
                {"input_column": "Sex", "reference_column": "Primary Gender"},
                {"input_column": "State", "reference_column": "State"},
                {"input_column": "UniqueID", "reference_column": "Record ID"},
            ]
        }
        result = score(output, _expected())
        assert result.correct == 3
        assert result.false_positives == 0
        assert result.missed_expected == []

    def test_partial_match(self) -> None:
        output = {
            "matches": [
                {"input_column": "Sex", "reference_column": "Primary Gender"},
                {"input_column": "State", "reference_column": "State"},
            ]
        }
        result = score(output, _expected())
        assert result.correct == 2
        assert result.false_positives == 0
        assert result.missed_expected == [("UniqueID", "Record ID")]

    def test_false_positive(self) -> None:
        output = {
            "matches": [
                {"input_column": "Sex", "reference_column": "Primary Gender"},
                {"input_column": "UniqueID", "reference_column": "Unique Life ID"},
            ]
        }
        result = score(output, _expected())
        assert result.correct == 1
        assert result.false_positives == 1
        assert result.incorrect_claims == [("UniqueID", "Unique Life ID")]

    def test_empty_matches(self) -> None:
        result = score({"matches": []}, _expected())
        assert result.correct == 0
        assert result.false_positives == 0
        assert len(result.missed_expected) == 3

    def test_missing_matches_key(self) -> None:
        result = score({}, _expected())
        assert result.correct == 0
