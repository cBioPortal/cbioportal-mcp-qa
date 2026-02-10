"""Tests for benchmark functionality."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from cbioportal_mcp_qa.benchmark import run_benchmark, regenerate_leaderboard


class TestRunBenchmark:
    """Test the run_benchmark function."""

    @pytest.mark.asyncio
    @patch('cbioportal_mcp_qa.benchmark.async_batch_main')
    @patch('cbioportal_mcp_qa.benchmark.run_evaluation_logic')
    @patch('cbioportal_mcp_qa.benchmark.regenerate_leaderboard')
    async def test_benchmark_basic_flow(self, mock_leaderboard, mock_eval, mock_batch, temp_dir):
        """Test basic benchmark flow without reproducibility."""
        mock_batch.return_value = None
        mock_eval.return_value = {
            "correctness_score": 2.5,
            "completeness_score": 3.0,
            "conciseness_score": 2.0,
            "faithfulness_score": 3.0
        }
        mock_leaderboard.return_value = None

        # Change to temp dir for this test
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create input CSV
            input_dir = temp_dir / "input"
            input_dir.mkdir()
            csv_path = input_dir / "benchmark-testing.csv"
            csv_path.write_text("Question Type,Question,DBBot Expected Answer\nTest,Q1?,A1\n")

            await run_benchmark(
                agent_type="test-agent",
                questions="1",
                api_key="test-key",
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
                include_sql=False,
                enable_open_telemetry_tracing=False,
                delay=0,
                batch_size=5,
                reproducibility_runs=0
            )

            # Verify batch processing was called
            assert mock_batch.called
            # Verify evaluation was called
            assert mock_eval.called
            # Verify leaderboard was regenerated
            assert mock_leaderboard.called

        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    @patch('cbioportal_mcp_qa.benchmark.async_batch_main')
    @patch('cbioportal_mcp_qa.benchmark.run_evaluation_logic')
    @patch('cbioportal_mcp_qa.benchmark.run_reproducibility_evaluation')
    @patch('cbioportal_mcp_qa.benchmark.regenerate_leaderboard')
    async def test_benchmark_with_reproducibility(self, mock_leaderboard, mock_repro_eval, mock_eval, mock_batch, temp_dir):
        """Test benchmark with reproducibility runs enabled."""
        mock_batch.return_value = None
        mock_eval.return_value = {
            "correctness_score": 2.5,
            "completeness_score": 3.0
        }
        mock_repro_eval.return_value = {
            "reproducibility_score": 2.8
        }
        mock_leaderboard.return_value = None

        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create input CSV
            input_dir = temp_dir / "input"
            input_dir.mkdir()
            csv_path = input_dir / "benchmark-testing.csv"
            csv_path.write_text("Question Type,Question,DBBot Expected Answer\nTest,Q1?,A1\n")

            await run_benchmark(
                agent_type="test-agent",
                questions="1",
                api_key="test-key",
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
                include_sql=False,
                enable_open_telemetry_tracing=False,
                delay=0,
                batch_size=5,
                reproducibility_runs=3
            )

            # Verify batch was called multiple times (1 main + 2 additional reproducibility runs, since run1 is symlinked)
            assert mock_batch.call_count == 3

            # Verify reproducibility evaluation was called
            assert mock_repro_eval.called

        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    @patch('cbioportal_mcp_qa.benchmark.async_batch_main')
    @patch('cbioportal_mcp_qa.benchmark.run_evaluation_logic')
    @patch('cbioportal_mcp_qa.benchmark.run_reproducibility_evaluation')
    @patch('cbioportal_mcp_qa.benchmark.regenerate_leaderboard')
    async def test_benchmark_creates_output_structure(self, mock_leaderboard, mock_repro_eval, mock_eval, mock_batch, temp_dir):
        """Test that benchmark creates proper directory structure."""
        mock_batch.return_value = None
        mock_eval.return_value = {"correctness_score": 2.5}
        mock_repro_eval.return_value = {"reproducibility_score": 2.8}
        mock_leaderboard.return_value = None

        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create input CSV
            input_dir = temp_dir / "input"
            input_dir.mkdir()
            csv_path = input_dir / "benchmark-testing.csv"
            csv_path.write_text("Question Type,Question,DBBot Expected Answer\nTest,Q1?,A1\n")

            await run_benchmark(
                agent_type="test-agent",
                questions="1",
                api_key="test-key",
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
                include_sql=False,
                enable_open_telemetry_tracing=False,
                delay=0,
                batch_size=5,
                reproducibility_runs=3
            )

            # Check directory structure
            results_dir = temp_dir / "results" / "test-agent"
            assert results_dir.exists()

            # Should have a date directory
            date_dirs = list(results_dir.iterdir())
            assert len(date_dirs) == 1

            date_dir = date_dirs[0]
            assert (date_dir / "answers").exists()
            assert (date_dir / "eval").exists()
            assert (date_dir / "reproducibility").exists()

            # Should have 3 reproducibility runs (run1 is symlinked, run2 and run3 are directories)
            repro_runs = list((date_dir / "reproducibility").iterdir())
            assert len(repro_runs) == 3
            # run1 is a symlink to answers dir
            assert (date_dir / "reproducibility" / "run1").is_symlink() or (date_dir / "reproducibility" / "run1").exists()
            # run2 and run3 are actual directories
            assert (date_dir / "reproducibility" / "run2").exists()
            assert (date_dir / "reproducibility" / "run3").exists()

        finally:
            os.chdir(original_cwd)


class TestRegenerateLeaderboard:
    """Test leaderboard regeneration."""

    def test_regenerate_leaderboard_creates_file(self, temp_dir, sample_evaluation_csv):
        """Test that regenerate_leaderboard creates LEADERBOARD.md."""
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results structure
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            # Copy sample evaluation CSV
            import shutil
            shutil.copy(sample_evaluation_csv, eval_dir / "evaluation_20260210.csv")

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            assert leaderboard_path.exists()

            content = leaderboard_path.read_text()
            assert "# Benchmark Leaderboard" in content
            assert "test-agent" in content

        finally:
            os.chdir(original_cwd)

    def test_regenerate_leaderboard_includes_scores(self, temp_dir, sample_evaluation_csv):
        """Test that leaderboard includes all score columns."""
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results structure
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            import shutil
            shutil.copy(sample_evaluation_csv, eval_dir / "evaluation_20260210.csv")

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Check for score column headers
            assert "Correctness Score" in content
            assert "Completeness Score" in content
            assert "Conciseness Score" in content
            assert "Faithfulness Score" in content

        finally:
            os.chdir(original_cwd)

    def test_regenerate_leaderboard_with_reproducibility(self, temp_dir, sample_evaluation_csv, sample_reproducibility_csv):
        """Test leaderboard includes reproducibility scores."""
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results structure
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            import shutil
            shutil.copy(sample_evaluation_csv, eval_dir / "evaluation_20260210.csv")
            shutil.copy(sample_reproducibility_csv, eval_dir / "reproducibility_20260210.csv")

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Should include reproducibility score
            assert "Reproducibility Score" in content

        finally:
            os.chdir(original_cwd)

    def test_regenerate_leaderboard_multiple_agents(self, temp_dir, sample_evaluation_csv):
        """Test leaderboard with multiple agents."""
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results for multiple agents
            for agent in ["agent1", "agent2"]:
                eval_dir = temp_dir / "results" / agent / "20260210" / "eval"
                eval_dir.mkdir(parents=True)

                import shutil
                shutil.copy(sample_evaluation_csv, eval_dir / "evaluation_20260210.csv")

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Both agents should be in leaderboard
            assert "agent1" in content
            assert "agent2" in content

        finally:
            os.chdir(original_cwd)

    def test_regenerate_leaderboard_sorts_by_date(self, temp_dir, sample_evaluation_csv):
        """Test that leaderboard is sorted by date descending."""
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results for different dates
            for date in ["20260208", "20260209", "20260210"]:
                eval_dir = temp_dir / "results" / "test-agent" / date / "eval"
                eval_dir.mkdir(parents=True)

                import shutil
                shutil.copy(sample_evaluation_csv, eval_dir / f"evaluation_{date}.csv")

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Most recent date should appear first
            pos_20260210 = content.index("20260210")
            pos_20260208 = content.index("20260208")
            assert pos_20260210 < pos_20260208

        finally:
            os.chdir(original_cwd)
