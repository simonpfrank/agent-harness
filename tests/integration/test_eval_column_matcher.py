"""Integration test — real run of the column-matcher capstone suite.

Requires ANTHROPIC_API_KEY; skipped otherwise. Zero mocks.
"""

from dotenv import load_dotenv

from eval.cases import load_cases, load_cells
from eval.report import rank, summarize
from eval.runner import run_repeated
from tests.integration.test_end_to_end import requires_anthropic_key

load_dotenv()


@requires_anthropic_key
class TestColumnMatcherCapstone:
    def test_real_run_produces_graded_results(self) -> None:
        cases = load_cases("eval/cases/column-matcher")
        cells = load_cells("eval/cells/column-matcher.yaml")
        assert len(cases) == 1
        assert len(cells) == 2

        case = cases[0]
        all_results = []
        for cell in cells:
            all_results.extend(run_repeated(case, cell, n=1))

        assert len(all_results) == 2
        for result in all_results:
            assert result.case_id == "pension-column-match"
            assert result.output_file_content is not None
            assert result.grades
            assert result.grades[0]["grader"] == "column_match"
            assert "correct" in result.grades[0]["detail"]

        summaries = summarize(all_results)
        ranked = rank(summaries, [("gate_pass_rate", "desc"), ("mean_cost", "asc")])
        assert len(ranked) == 2
