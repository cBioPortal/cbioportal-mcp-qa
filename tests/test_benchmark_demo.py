"""
Fixture-based benchmark demonstration test.

This test demonstrates the full benchmark pipeline using pre-recorded fixture data.
No API keys required - runs in under 5 seconds using mocks.
"""

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cbioportal_mcp_qa.benchmark import run_benchmark


class TestBenchmarkDemo:
    """Demonstrate full benchmark pipeline with fixtures and mocks."""

    @pytest.mark.asyncio
    @patch('cbioportal_mcp_qa.benchmark.AGENT_COLUMN_MAPPING', {"demo-agent": "DBBot Expected Answer"})
    @patch('cbioportal_mcp_qa.benchmark.async_batch_main')
    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    async def test_full_benchmark_pipeline_with_reproducibility(
        self, mock_get_client, mock_batch, temp_dir, capsys
    ):
        """
        End-to-end benchmark demonstration using real fixture data.

        This test:
        1. Uses pre-recorded answers from results/cbio-mcp-agent/20260128/
        2. Mocks the QA client (batch processor) to copy fixture answers
        3. Mocks the Anthropic client for evaluation
        4. Runs full pipeline including 3 reproducibility runs
        5. Generates leaderboard with both eval and reproducibility scores
        6. Prints clear progress output showing each step

        Completes in < 5 seconds with no API keys needed.
        """

        # Setup: Create mock Anthropic client for evaluation
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def mock_anthropic_evaluation(**kwargs):
            """Mock Anthropic API calls for evaluation and reproducibility."""
            prompt = kwargs.get('messages', [{}])[0].get('content', '')

            # Standard evaluation (4 criteria)
            if 'Correctness' in prompt and 'Completeness' in prompt:
                response = MagicMock()
                response.content = [MagicMock()]
                # Extract question from prompt for variety
                if 'studies' in prompt.lower():
                    response.content[0].text = json.dumps({
                        "question": "How many studies are in cBioPortal?",
                        "correctness_score": 3,
                        "correctness_explanation": "Perfectly accurate count",
                        "completeness_score": 3,
                        "completeness_explanation": "Fully answers the question",
                        "conciseness_score": 3,
                        "conciseness_explanation": "Very concise",
                        "faithfulness_score": 3,
                        "faithfulness_explanation": "Based on database query"
                    })
                elif 'patients' in prompt.lower() or 'samples' in prompt.lower():
                    response.content[0].text = json.dumps({
                        "question": "How many patients and samples?",
                        "correctness_score": 3,
                        "correctness_explanation": "Accurate patient and sample counts",
                        "completeness_score": 3,
                        "completeness_explanation": "Complete answer",
                        "conciseness_score": 2,
                        "conciseness_explanation": "Slightly verbose",
                        "faithfulness_score": 3,
                        "faithfulness_explanation": "Database-derived"
                    })
                else:
                    # Generic good score
                    response.content[0].text = json.dumps({
                        "question": "Generic question",
                        "correctness_score": 3,
                        "correctness_explanation": "Accurate",
                        "completeness_score": 3,
                        "completeness_explanation": "Complete",
                        "conciseness_score": 2,
                        "conciseness_explanation": "Mostly concise",
                        "faithfulness_score": 3,
                        "faithfulness_explanation": "Based on context"
                    })
                return response

            # Reproducibility pairwise consistency check
            elif 'consistency' in prompt.lower() or 'Output A:' in prompt:
                response = MagicMock()
                response.content = [MagicMock()]
                # High consistency for reproducibility (semantically equivalent)
                response.content[0].text = json.dumps({
                    "consistency_score": 3,
                    "consistency_explanation": "Both outputs convey identical information with only minor wording differences"
                })
                return response

            # Default fallback
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = json.dumps({
                "error": "Unknown prompt type"
            })
            return response

        mock_client.messages.create = mock_anthropic_evaluation

        # Setup: Create fixture answer directory
        fixture_source = Path(__file__).parent.parent / "results" / "cbio-mcp-agent" / "20260128" / "answers"

        # Mock batch processor to copy real fixture files instead of calling agent
        run_counter = {"count": 0}  # Track which run we're on

        def mock_batch_processor(**kwargs):
            """Copy fixture answers to simulate agent responses."""
            output_dir = Path(kwargs['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)

            run_counter["count"] += 1
            current_run = run_counter["count"]

            # Copy a subset of real answers (questions 1-3)
            for i in [1, 2, 3]:
                src_file = fixture_source / f"{i}.md"
                if src_file.exists():
                    # Copy the file
                    dest_file = output_dir / f"{i}.md"
                    shutil.copy(src_file, dest_file)

                    # For run2 and run3, slightly modify the content to create variation
                    # This simulates semantic equivalence with different wording
                    if current_run > 1:
                        content = dest_file.read_text()
                        # Add a small variation marker (but keep semantic meaning identical)
                        modified_content = content.replace(
                            "There are **511 studies**",
                            "cBioPortal contains **511 studies**" if current_run == 2 else "The total is **511 studies**"
                        ).replace(
                            "The **MSK-CHORD Study** contains:",
                            "MSK-CHORD contains:" if current_run == 2 else "The MSK-CHORD Study has:"
                        )
                        dest_file.write_text(modified_content)

                    print(f"[DEMO] Copied fixture answer {i}.md (run {current_run})")

        mock_batch.side_effect = mock_batch_processor

        # Setup: Create input CSV with subset of questions
        input_dir = temp_dir / "input"
        input_dir.mkdir()
        csv_path = input_dir / "benchmark-testing.csv"

        csv_content = """Question Type,Study,Question,DBBot Expected Answer
Data Discovery,All Studies,How many studies are in cBioPortal?,511 studies
Cohort Statistics,msk_chord_2024,How many patients and samples are in the MSK-CHORD Study?,"24,950 Patients and 25,040 samples"
Clinical Data,msk_chord_2024,How many primary samples are in the MSK-CHORD Study?,"15,928 primary samples"
"""
        csv_path.write_text(csv_content)

        # Change to temp directory for test execution
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            print("\n" + "=" * 70)
            print("BENCHMARK DEMONSTRATION - Full Pipeline with Reproducibility")
            print("=" * 70)

            # Execute benchmark with reproducibility
            await run_benchmark(
                agent_type="demo-agent",
                questions="1-3",
                api_key="mock-key",
                clickhouse_host=None,
                clickhouse_database=None,
                clickhouse_port=None,
                clickhouse_user=None,
                clickhouse_password=None,
                clickhouse_secure=None,
                clickhouse_verify=None,
                clickhouse_connect_timeout=None,
                clickhouse_send_receive_timeout=None,
                model="claude-sonnet-4",
                use_ollama=False,
                ollama_base_url="http://localhost:11434",
                use_bedrock=False,
                aws_profile=None,
                include_sql=False,
                enable_open_telemetry_tracing=False,
                delay=0,
                batch_size=5,
                skip_eval=False,
                eval_only=False,
                reproducibility_runs=3  # Enable reproducibility testing
            )

            print("\n" + "=" * 70)
            print("VERIFICATION: Checking Generated Artifacts")
            print("=" * 70)

            # Verify directory structure
            results_dir = temp_dir / "results" / "demo-agent"
            assert results_dir.exists(), "Results directory not created"
            print("[PASS] Results directory created")

            # Find the date directory
            date_dirs = list(results_dir.iterdir())
            assert len(date_dirs) == 1, f"Expected 1 date dir, found {len(date_dirs)}"
            date_dir = date_dirs[0]
            print(f"[PASS] Date directory: {date_dir.name}")

            # Verify main directories
            answers_dir = date_dir / "answers"
            eval_dir = date_dir / "eval"
            repro_dir = date_dir / "reproducibility"

            assert answers_dir.exists(), "Answers directory not created"
            print("[PASS] Answers directory exists")

            assert eval_dir.exists(), "Evaluation directory not created"
            print("[PASS] Evaluation directory exists")

            assert repro_dir.exists(), "Reproducibility directory not created"
            print("[PASS] Reproducibility directory exists")

            # Verify answer files
            answer_files = list(answers_dir.glob("*.md"))
            assert len(answer_files) == 3, f"Expected 3 answer files, found {len(answer_files)}"
            print(f"[PASS] Generated {len(answer_files)} answer files: {[f.name for f in answer_files]}")

            # Verify reproducibility runs
            run_dirs = sorted([d for d in repro_dir.iterdir() if d.is_dir() or d.is_symlink()])
            assert len(run_dirs) == 3, f"Expected 3 runs, found {len(run_dirs)}"
            print(f"[PASS] Generated {len(run_dirs)} reproducibility runs")

            # Verify run1 is symlink (reuses main answers)
            run1 = repro_dir / "run1"
            assert run1.is_symlink() or run1.exists(), "run1 should exist (symlink or directory)"
            print("[PASS] run1 exists (reuses main answers)")

            # Verify run2 and run3 have answers
            for run_idx in [2, 3]:
                run_path = repro_dir / f"run{run_idx}"
                assert run_path.exists(), f"run{run_idx} directory not created"
                run_answers = list(run_path.glob("*.md"))
                assert len(run_answers) == 3, f"run{run_idx} should have 3 answers"
                print(f"[PASS] run{run_idx} has {len(run_answers)} answer files")

            # Verify evaluation CSV
            eval_csvs = list(eval_dir.glob("evaluation_*.csv"))
            assert len(eval_csvs) == 1, f"Expected 1 evaluation CSV, found {len(eval_csvs)}"
            eval_csv = eval_csvs[0]
            print(f"[PASS] Evaluation CSV created: {eval_csv.name}")

            # Check evaluation content
            eval_df = pd.read_csv(eval_csv, comment='#')
            assert len(eval_df) == 3, f"Expected 3 evaluation rows, found {len(eval_df)}"
            print(f"[PASS] Evaluation CSV has {len(eval_df)} question evaluations")

            # Verify evaluation scores are present
            expected_score_cols = [
                'correctness_score', 'completeness_score',
                'conciseness_score', 'faithfulness_score'
            ]
            for col in expected_score_cols:
                assert col in eval_df.columns, f"Missing score column: {col}"
            print(f"[PASS] All expected score columns present: {expected_score_cols}")

            # Verify reproducibility CSV
            repro_csvs = list(eval_dir.glob("reproducibility_*.csv"))
            assert len(repro_csvs) == 1, f"Expected 1 reproducibility CSV, found {len(repro_csvs)}"
            repro_csv = repro_csvs[0]
            print(f"[PASS] Reproducibility CSV created: {repro_csv.name}")

            # Check reproducibility content
            repro_df = pd.read_csv(repro_csv, comment='#')
            assert len(repro_df) == 3, f"Expected 3 reproducibility rows, found {len(repro_df)}"
            print(f"[PASS] Reproducibility CSV has {len(repro_df)} question evaluations")

            # Verify reproducibility score column
            assert 'reproducibility_score' in repro_df.columns, "Missing reproducibility_score column"
            print("[PASS] Reproducibility score column present")

            # Verify pairwise comparison columns exist (should have at least one)
            pairwise_cols = [col for col in repro_df.columns if '_vs_' in col and col.endswith('_score')]
            assert len(pairwise_cols) >= 1, f"Should have at least 1 pairwise comparison column, found {len(pairwise_cols)}"
            print(f"[PASS] Pairwise comparison columns present: {pairwise_cols}")

            # Verify leaderboard
            leaderboard_path = temp_dir / "LEADERBOARD.md"
            assert leaderboard_path.exists(), "Leaderboard not created"
            print("[PASS] LEADERBOARD.md created")

            # Check leaderboard content
            leaderboard_content = leaderboard_path.read_text()
            assert "# Benchmark Leaderboard" in leaderboard_content, "Missing leaderboard title"
            assert "demo-agent" in leaderboard_content, "demo-agent not in leaderboard"
            print("[PASS] Leaderboard contains demo-agent entry")

            # Verify leaderboard has all score columns
            assert "Correctness Score" in leaderboard_content, "Missing Correctness Score in leaderboard"
            assert "Completeness Score" in leaderboard_content, "Missing Completeness Score in leaderboard"
            assert "Conciseness Score" in leaderboard_content, "Missing Conciseness Score in leaderboard"
            assert "Faithfulness Score" in leaderboard_content, "Missing Faithfulness Score in leaderboard"
            assert "Reproducibility Score" in leaderboard_content, "Missing Reproducibility Score in leaderboard"
            print("[PASS] Leaderboard includes all score columns (eval + reproducibility)")

            # Display leaderboard
            print("\n" + "=" * 70)
            print("GENERATED LEADERBOARD")
            print("=" * 70)
            print(leaderboard_content)

            # Display sample evaluation scores
            print("\n" + "=" * 70)
            print("SAMPLE EVALUATION SCORES")
            print("=" * 70)
            print(f"\nEvaluation Scores (first question):")
            print(eval_df.iloc[0].to_dict())
            print(f"\nReproducibility Scores (first question):")
            print(repro_df.iloc[0].to_dict())

            print("\n" + "=" * 70)
            print("DEMO TEST COMPLETE - ALL CHECKS PASSED")
            print("=" * 70)
            print(f"\nBenchmark artifacts generated in: {date_dir}")
            print(f"  - {len(answer_files)} answer files")
            print(f"  - {len(run_dirs)} reproducibility runs")
            print(f"  - Evaluation CSV with {len(eval_df)} questions")
            print(f"  - Reproducibility CSV with {len(repro_df)} questions")
            print(f"  - Leaderboard with eval + reproducibility scores")
            print("\nThis demonstrates the full benchmark pipeline without API keys!")

        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    @patch('cbioportal_mcp_qa.benchmark.AGENT_COLUMN_MAPPING', {"quick-demo": "DBBot Expected Answer"})
    @patch('cbioportal_mcp_qa.benchmark.async_batch_main')
    @patch('cbioportal_mcp_qa.evaluation.get_anthropic_client')
    async def test_quick_benchmark_no_reproducibility(
        self, mock_get_client, mock_batch, temp_dir
    ):
        """
        Quick benchmark test without reproducibility (faster variant).

        Demonstrates basic pipeline without reproducibility runs.
        Even faster - completes in ~1 second.
        """

        # Setup mock clients
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def mock_evaluation(**kwargs):
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = json.dumps({
                "question": "Test question",
                "correctness_score": 3,
                "correctness_explanation": "Accurate",
                "completeness_score": 3,
                "completeness_explanation": "Complete",
                "conciseness_score": 3,
                "conciseness_explanation": "Concise",
                "faithfulness_score": 3,
                "faithfulness_explanation": "Based on context"
            })
            return response

        mock_client.messages.create = mock_evaluation

        # Mock batch to create dummy answers
        def mock_batch_processor(**kwargs):
            output_dir = Path(kwargs['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
            for i in [1]:
                (output_dir / f"{i}.md").write_text(f"# Question {i}\n\n**Answer:** Test answer {i}")

        mock_batch.side_effect = mock_batch_processor

        # Create input CSV
        input_dir = temp_dir / "input"
        input_dir.mkdir()
        csv_path = input_dir / "benchmark-testing.csv"
        csv_path.write_text("Question Type,Study,Question,DBBot Expected Answer\nTest,All,Test?,Test answer\n")

        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Run benchmark without reproducibility
            await run_benchmark(
                agent_type="quick-demo",
                questions="1",
                api_key="mock-key",
                clickhouse_host=None,
                clickhouse_database=None,
                clickhouse_port=None,
                clickhouse_user=None,
                clickhouse_password=None,
                clickhouse_secure=None,
                clickhouse_verify=None,
                clickhouse_connect_timeout=None,
                clickhouse_send_receive_timeout=None,
                model="claude-sonnet-4",
                use_ollama=False,
                ollama_base_url="http://localhost:11434",
                use_bedrock=False,
                aws_profile=None,
                include_sql=False,
                enable_open_telemetry_tracing=False,
                delay=0,
                batch_size=5,
                skip_eval=False,
                eval_only=False,
                reproducibility_runs=0  # No reproducibility
            )

            # Verify basic structure
            results_dir = temp_dir / "results" / "quick-demo"
            assert results_dir.exists()

            date_dirs = list(results_dir.iterdir())
            assert len(date_dirs) == 1
            date_dir = date_dirs[0]

            # Should have answers and eval, but no reproducibility
            assert (date_dir / "answers").exists()
            assert (date_dir / "eval").exists()

            # Reproducibility dir exists but empty (created by benchmark.py but not populated)
            repro_dir = date_dir / "reproducibility"
            if repro_dir.exists():
                # Should be empty or not exist
                run_dirs = list(repro_dir.iterdir())
                assert len(run_dirs) == 0, "Should not have reproducibility runs when reproducibility_runs=0"

            # Should have evaluation CSV
            eval_csvs = list((date_dir / "eval").glob("evaluation_*.csv"))
            assert len(eval_csvs) == 1

            # Should NOT have reproducibility CSV
            repro_csvs = list((date_dir / "eval").glob("reproducibility_*.csv"))
            assert len(repro_csvs) == 0, "Should not have reproducibility CSV when reproducibility_runs=0"

            # Leaderboard should exist with only eval scores
            leaderboard_path = temp_dir / "LEADERBOARD.md"
            assert leaderboard_path.exists()

            content = leaderboard_path.read_text()
            assert "quick-demo" in content
            assert "Correctness Score" in content
            # Should NOT have reproducibility score
            assert "Reproducibility Score" not in content

        finally:
            os.chdir(original_cwd)
