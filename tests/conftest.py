"""Pytest configuration and shared fixtures."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_csv_path(temp_dir):
    """Create a sample CSV file for testing."""
    csv_content = """Question Type,Study,Question,DBBot Expected Answer
Data Discovery,All Studies,How many studies are in cBioPortal?,492 studies
Cohort Statistics,msk_chord_2024,How many patients are in MSK-CHORD?,10564 patients
Genomic Alteration Frequencies,os_target_gdc,What are the top 5 mutated genes?,"TP53 22.4%, MUC16 11.2%, TTN 11.2%, ATRX 7.7%, DNAH9 7.0%"
"""
    csv_path = temp_dir / "test_questions.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_csv_with_question_id(temp_dir):
    """Create a sample CSV file with Question ID column."""
    csv_content = """#,Question Type,Study,Question,DBBot Expected Answer
1,Data Discovery,All Studies,How many studies are in cBioPortal?,492 studies
2,Cohort Statistics,msk_chord_2024,How many patients are in MSK-CHORD?,10564 patients
3,Genomic Alteration Frequencies,os_target_gdc,What are the top 5 mutated genes?,"TP53 22.4%, MUC16 11.2%, TTN 11.2%, ATRX 7.7%, DNAH9 7.0%"
"""
    csv_path = temp_dir / "test_questions_with_id.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client for testing evaluation."""
    client = MagicMock()

    def mock_create(**kwargs):
        """Mock message creation with appropriate responses."""
        prompt = kwargs.get('messages', [{}])[0].get('content', '')

        # Mock evaluation responses
        if 'Correctness' in prompt and 'Completeness' in prompt:
            # Standard evaluation
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = json.dumps({
                "question": "Test question",
                "correctness_score": 3,
                "correctness_explanation": "Perfectly accurate answer",
                "completeness_score": 3,
                "completeness_explanation": "Fully addresses the question",
                "conciseness_score": 2,
                "conciseness_explanation": "Mostly concise with minor verbosity",
                "faithfulness_score": 3,
                "faithfulness_explanation": "Based solely on provided context"
            })
            return response

        # Mock pairwise consistency check for reproducibility
        elif 'consistency' in prompt.lower():
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = json.dumps({
                "consistency_score": 3,
                "consistency_explanation": "Both outputs convey identical information"
            })
            return response

        # Default response
        response = MagicMock()
        response.content = [MagicMock()]
        response.content[0].text = '{"error": "Unknown prompt type"}'
        return response

    client.messages.create = mock_create
    return client


@pytest.fixture
def mock_qa_client():
    """Create a mock QA client that simulates agent responses."""
    client = AsyncMock()

    async def mock_ask_question(question: str) -> str:
        """Return appropriate mock answers based on question."""
        if "how many studies" in question.lower():
            return "There are 492 studies in cBioPortal."
        elif "how many patients" in question.lower():
            return "There are 10564 patients who have glioblastoma in the MSK-CHORD study."
        elif "top 5" in question.lower():
            return "The top 5 most frequently mutated genes are: TP53 (22.4%), MUC16 (11.2%), TTN (11.2%), ATRX (7.7%), DNAH9 (7.0%)"
        else:
            return "Mock answer for test question."

    client.ask_question = mock_ask_question
    client.get_sql_queries = MagicMock(return_value=[])
    client.get_sql_queries_markdown = MagicMock(return_value="")
    return client


@pytest.fixture
def sample_answers_dir(temp_dir):
    """Create a directory with sample answer files."""
    answers_dir = temp_dir / "answers"
    answers_dir.mkdir()

    # Create sample answer files
    answers = {
        "1.md": "There are 492 studies in cBioPortal.",
        "2.md": "There are 10564 patients who have glioblastoma in the MSK-CHORD study.",
        "3.md": "The top 5 most frequently mutated genes are: TP53 (22.4%), MUC16 (11.2%), TTN (11.2%), ATRX (7.7%), DNAH9 (7.0%)"
    }

    for filename, content in answers.items():
        (answers_dir / filename).write_text(content)

    return answers_dir


@pytest.fixture
def sample_reproducibility_runs(temp_dir):
    """Create sample reproducibility run directories with slightly different wordings."""
    repro_dir = temp_dir / "reproducibility"

    # Create 3 runs with semantically equivalent but differently worded answers
    runs_data = {
        "run1": {
            "1.md": "There are 492 studies in cBioPortal.",
            "2.md": "The MSK-CHORD study contains 10564 patients with glioblastoma.",
        },
        "run2": {
            "1.md": "cBioPortal contains a total of 492 studies.",
            "2.md": "Glioblastoma patients total 10564 in the MSK-CHORD study.",
        },
        "run3": {
            "1.md": "The total number of studies in cBioPortal is 492.",
            "2.md": "In MSK-CHORD, there are 10564 patients who have glioblastoma.",
        }
    }

    for run_name, answers in runs_data.items():
        run_dir = repro_dir / run_name
        run_dir.mkdir(parents=True)
        for filename, content in answers.items():
            (run_dir / filename).write_text(content)

    return repro_dir


@pytest.fixture
def sample_evaluation_csv(temp_dir):
    """Create a sample evaluation CSV file."""
    eval_content = """# Average correctness_score: 2.67,,,,,,,,
# Average completeness_score: 3.00,,,,,,,,
# Average conciseness_score: 2.33,,,,,,,,
# Average faithfulness_score: 3.00,,,,,,,,
question,correctness_score,correctness_explanation,completeness_score,completeness_explanation,conciseness_score,conciseness_explanation,faithfulness_score,faithfulness_explanation
How many studies are in cBioPortal?,3,Perfectly accurate,3,Fully addresses the question,2,Mostly concise,3,Based on database
How many patients are in MSK-CHORD?,2,Mostly accurate,3,Complete answer,3,Very concise,3,No hallucinations
What are the top 5 mutated genes?,3,Correct information,3,All 5 genes provided,2,Some verbosity,3,Database derived
"""
    eval_path = temp_dir / "evaluation_20260210.csv"
    eval_path.write_text(eval_content)
    return eval_path


@pytest.fixture
def sample_reproducibility_csv(temp_dir):
    """Create a sample reproducibility evaluation CSV file."""
    repro_content = """# Average reproducibility_score: 2.85
question,reproducibility_score,reproducibility_explanation,run1_vs_run2_score,run1_vs_run3_score,run2_vs_run3_score
How many studies are in cBioPortal?,3.0,Average of 3 pairwise comparisons,3,3,3
How many patients are in MSK-CHORD?,2.7,Average of 3 pairwise comparisons,3,3,2
"""
    repro_path = temp_dir / "reproducibility_20260210.csv"
    repro_path.write_text(repro_content)
    return repro_path


@pytest.fixture
def mock_semantic_consistency_client():
    """Mock Anthropic client that validates semantic equivalence."""
    client = MagicMock()

    def mock_create(**kwargs):
        """Mock that scores semantic consistency correctly."""
        prompt = kwargs.get('messages', [{}])[0].get('content', '')

        # Extract outputs from prompt
        if 'Output A:' in prompt and 'Output B:' in prompt:
            # Parse outputs
            parts = prompt.split('Output A:')[1].split('Output B:')
            output_a = parts[0].strip()
            output_b = parts[1].strip().split('\n\nInstructions:')[0].strip()

            # Check for semantic equivalence
            # Both say 492 studies
            if '492' in output_a and '492' in output_b and 'stud' in output_a.lower() and 'stud' in output_b.lower():
                score = 3
                explanation = "Both outputs report 492 studies - semantically identical"
            # Both say 10564 patients with glioblastoma
            elif '10564' in output_a and '10564' in output_b and 'glioblastoma' in output_a.lower() and 'glioblastoma' in output_b.lower():
                score = 3
                explanation = "Both outputs report the same number of glioblastoma patients - semantically equivalent"
            else:
                score = 2
                explanation = "Outputs are similar but with some differences"

            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = json.dumps({
                "consistency_score": score,
                "consistency_explanation": explanation
            })
            return response

        # Default
        response = MagicMock()
        response.content = [MagicMock()]
        response.content[0].text = json.dumps({
            "consistency_score": 1,
            "consistency_explanation": "Unable to parse outputs"
        })
        return response

    client.messages.create = mock_create
    return client


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
