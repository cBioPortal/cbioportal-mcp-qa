"""Tests for evaluation functionality."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cbioportal_mcp_qa.evaluation import (
    evaluate,
    extract_answer_content,
    run_evaluation_logic,
    evaluate_pairwise_consistency,
    run_reproducibility_evaluation
)


class TestExtractAnswerContent:
    """Test the extract_answer_content helper function."""

    def test_extracts_answer_from_full_markdown(self):
        """Test extraction from a typical markdown answer file."""
        markdown = """# Question 1

**Type:** Data Discovery
**Question:** How many studies are in cBioPortal?

**Answer:**

There are **511 studies** in cBioPortal.

---

**Model:** claude-sonnet-4
**Timestamp:** 2026-01-28 10:00:00
"""
        result = extract_answer_content(markdown)
        assert "511 studies" in result
        assert "Model:" not in result
        assert "Timestamp:" not in result
        assert "Type:" not in result

    def test_strips_sql_query_blocks(self):
        """Test that SQL tool call blocks are removed."""
        markdown = """**Answer:**

The study has 24,950 patients.

Calling `execute_query` with args:
```json
{"query": "SELECT COUNT(*) FROM patient"}
```
Result from `execute_query`:
```json
{"count": 24950}
```

So the answer is 24,950 patients.

---
"""
        result = extract_answer_content(markdown)
        assert "24,950 patients" in result
        assert "execute_query" not in result
        assert "SELECT COUNT" not in result

    def test_fallback_when_no_answer_section(self):
        """Test fallback when **Answer:** marker is missing."""
        plain_text = "This is just plain text without any answer markers."
        result = extract_answer_content(plain_text)
        assert result == plain_text

    def test_handles_answer_with_no_trailing_separator(self):
        """Test extraction when there's no --- separator at the end."""
        markdown = """**Answer:**

There are 492 studies in cBioPortal."""
        result = extract_answer_content(markdown)
        assert "492 studies" in result


class TestEvaluate:
    """Test the evaluate function."""

    def test_evaluate_returns_json(self, mock_anthropic_client):
        """Test that evaluate returns valid JSON structure."""
        result = evaluate(
            client=mock_anthropic_client,
            question="How many studies?",
            expected="492 studies",
            output="There are 492 studies in cBioPortal."
        )

        assert isinstance(result, dict)
        assert "correctness_score" in result
        assert "completeness_score" in result
        assert "conciseness_score" in result
        assert "faithfulness_score" in result

    def test_evaluate_includes_explanations(self, mock_anthropic_client):
        """Test that evaluate includes explanation fields."""
        result = evaluate(
            client=mock_anthropic_client,
            question="Test question?",
            expected="Expected answer",
            output="Actual output"
        )

        assert "correctness_explanation" in result
        assert "completeness_explanation" in result
        assert "conciseness_explanation" in result
        assert "faithfulness_explanation" in result

    def test_evaluate_scores_are_numeric(self, mock_anthropic_client):
        """Test that score values are numeric."""
        result = evaluate(
            client=mock_anthropic_client,
            question="Test?",
            expected="Answer",
            output="Output"
        )

        assert isinstance(result["correctness_score"], (int, float))
        assert isinstance(result["completeness_score"], (int, float))
        assert isinstance(result["conciseness_score"], (int, float))
        assert isinstance(result["faithfulness_score"], (int, float))


class TestRunEvaluationLogic:
    """Test the run_evaluation_logic function."""

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_run_evaluation_basic(self, mock_get_client, sample_csv_path, sample_answers_dir, temp_dir, mock_anthropic_client):
        """Test basic evaluation logic."""
        mock_get_client.return_value = mock_anthropic_client

        output_dir = temp_dir / "eval"

        metrics = run_evaluation_logic(
            input_csv=str(sample_csv_path),
            answers_dir=str(sample_answers_dir),
            output_dir=str(output_dir),
            answer_column="DBBot Expected Answer"
        )

        assert isinstance(metrics, dict)
        assert "correctness_score" in metrics
        assert "completeness_score" in metrics
        assert "conciseness_score" in metrics
        assert "faithfulness_score" in metrics

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_run_evaluation_creates_csv(self, mock_get_client, sample_csv_path, sample_answers_dir, temp_dir, mock_anthropic_client):
        """Test that evaluation creates output CSV."""
        mock_get_client.return_value = mock_anthropic_client

        output_dir = temp_dir / "eval"

        run_evaluation_logic(
            input_csv=str(sample_csv_path),
            answers_dir=str(sample_answers_dir),
            output_dir=str(output_dir),
            answer_column="DBBot Expected Answer"
        )

        # Check that CSV was created
        csv_files = list(Path(output_dir).glob("evaluation_*.csv"))
        assert len(csv_files) == 1

        # Verify CSV structure
        df = pd.read_csv(csv_files[0], comment='#')
        assert "question" in df.columns
        assert "correctness_score" in df.columns
        assert "completeness_score" in df.columns

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_run_evaluation_with_missing_answer_column(self, mock_get_client, sample_csv_path, sample_answers_dir, temp_dir, mock_anthropic_client):
        """Test evaluation with missing answer column."""
        mock_get_client.return_value = mock_anthropic_client

        output_dir = temp_dir / "eval"

        metrics = run_evaluation_logic(
            input_csv=str(sample_csv_path),
            answers_dir=str(sample_answers_dir),
            output_dir=str(output_dir),
            answer_column="NonexistentColumn"
        )

        # Should return empty dict when column doesn't exist
        assert metrics == {}

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_run_evaluation_calculates_averages(self, mock_get_client, sample_csv_path, sample_answers_dir, temp_dir, mock_anthropic_client):
        """Test that evaluation calculates average scores correctly."""
        mock_get_client.return_value = mock_anthropic_client

        output_dir = temp_dir / "eval"

        metrics = run_evaluation_logic(
            input_csv=str(sample_csv_path),
            answers_dir=str(sample_answers_dir),
            output_dir=str(output_dir),
            answer_column="DBBot Expected Answer"
        )

        # All scores should be between 1 and 3
        for key, value in metrics.items():
            assert 1.0 <= value <= 3.0


class TestEvaluatePairwiseConsistency:
    """Test pairwise consistency evaluation."""

    def test_evaluate_pairwise_returns_dict(self, mock_semantic_consistency_client):
        """Test that pairwise consistency returns a dict."""
        result = evaluate_pairwise_consistency(
            client=mock_semantic_consistency_client,
            question="How many studies?",
            output1="There are 492 studies.",
            output2="cBioPortal has 492 studies."
        )

        assert isinstance(result, dict)
        assert "consistency_score" in result
        assert "consistency_explanation" in result

    def test_evaluate_pairwise_semantic_equivalence(self, mock_semantic_consistency_client):
        """Test that semantically equivalent answers score highly."""
        # Two differently worded but semantically identical answers
        result = evaluate_pairwise_consistency(
            client=mock_semantic_consistency_client,
            question="How many patients with glioblastoma?",
            output1="There are 10564 patients who have glioblastoma.",
            output2="Glioblastoma patients total 10564."
        )

        # Should score as consistent (score 3)
        assert result["consistency_score"] == 3

    def test_evaluate_pairwise_identical_numbers(self, mock_semantic_consistency_client):
        """Test that identical numerical answers are recognized."""
        result = evaluate_pairwise_consistency(
            client=mock_semantic_consistency_client,
            question="How many studies?",
            output1="There are 492 studies in cBioPortal.",
            output2="cBioPortal contains a total of 492 studies."
        )

        assert result["consistency_score"] == 3


class TestRunReproducibilityEvaluation:
    """Test reproducibility evaluation."""

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_reproducibility_evaluation_basic(self, mock_get_client, sample_csv_path, sample_reproducibility_runs, temp_dir, mock_semantic_consistency_client):
        """Test basic reproducibility evaluation."""
        mock_get_client.return_value = mock_semantic_consistency_client

        output_dir = temp_dir / "eval"

        metrics = run_reproducibility_evaluation(
            input_csv=str(sample_csv_path),
            reproducibility_dir=str(sample_reproducibility_runs),
            output_dir=str(output_dir),
            num_runs=3
        )

        assert isinstance(metrics, dict)
        assert "reproducibility_score" in metrics

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_reproducibility_creates_csv(self, mock_get_client, sample_csv_path, sample_reproducibility_runs, temp_dir, mock_semantic_consistency_client):
        """Test that reproducibility evaluation creates CSV."""
        mock_get_client.return_value = mock_semantic_consistency_client

        output_dir = temp_dir / "eval"

        run_reproducibility_evaluation(
            input_csv=str(sample_csv_path),
            reproducibility_dir=str(sample_reproducibility_runs),
            output_dir=str(output_dir),
            num_runs=3
        )

        csv_files = list(Path(output_dir).glob("reproducibility_*.csv"))
        assert len(csv_files) == 1

        # Verify CSV structure
        df = pd.read_csv(csv_files[0], comment='#')
        assert "question" in df.columns
        assert "reproducibility_score" in df.columns

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_reproducibility_semantic_equivalence(self, mock_get_client, sample_csv_path, sample_reproducibility_runs, temp_dir, mock_semantic_consistency_client):
        """Test that reproducibility correctly identifies semantic equivalence."""
        mock_get_client.return_value = mock_semantic_consistency_client

        output_dir = temp_dir / "eval"

        metrics = run_reproducibility_evaluation(
            input_csv=str(sample_csv_path),
            reproducibility_dir=str(sample_reproducibility_runs),
            output_dir=str(output_dir),
            num_runs=3
        )

        # With 3 runs and semantically equivalent answers, should score high
        # (Each pairwise comparison should score 3, average = 3.0)
        assert metrics["reproducibility_score"] >= 2.5

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_reproducibility_with_different_wordings(self, mock_get_client, temp_dir, sample_csv_path, mock_semantic_consistency_client):
        """Test reproducibility with various phrasings of same fact."""
        # Create runs with different wordings
        repro_dir = temp_dir / "repro_test"

        # All convey same information: "10564 patients who have glioblastoma"
        variations = {
            "run1": {"2.md": "There are 10564 patients who have glioblastoma in MSK-CHORD."},
            "run2": {"2.md": "Glioblastoma patients total 10564 in the MSK-CHORD study."},
            "run3": {"2.md": "The MSK-CHORD study contains 10564 patients with glioblastoma."}
        }

        for run_name, answers in variations.items():
            run_dir = repro_dir / run_name
            run_dir.mkdir(parents=True)
            for filename, content in answers.items():
                (run_dir / filename).write_text(content)

        mock_get_client.return_value = mock_semantic_consistency_client

        output_dir = temp_dir / "eval"

        metrics = run_reproducibility_evaluation(
            input_csv=str(sample_csv_path),
            reproducibility_dir=str(repro_dir),
            output_dir=str(output_dir),
            num_runs=3
        )

        # Should recognize semantic equivalence despite different wording
        assert metrics["reproducibility_score"] >= 2.5

    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    def test_reproducibility_pairwise_comparisons(self, mock_get_client, sample_csv_path, sample_reproducibility_runs, temp_dir, mock_semantic_consistency_client):
        """Test that reproducibility performs all pairwise comparisons."""
        mock_get_client.return_value = mock_semantic_consistency_client

        output_dir = temp_dir / "eval"

        run_reproducibility_evaluation(
            input_csv=str(sample_csv_path),
            reproducibility_dir=str(sample_reproducibility_runs),
            output_dir=str(output_dir),
            num_runs=3
        )

        csv_files = list(Path(output_dir).glob("reproducibility_*.csv"))
        df = pd.read_csv(csv_files[0], comment='#')

        # With 3 runs, should have pairwise comparison columns: run1_vs_run2, run1_vs_run3, run2_vs_run3
        pairwise_cols = [col for col in df.columns if '_vs_' in col]
        assert len(pairwise_cols) == 3
