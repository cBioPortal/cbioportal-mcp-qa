"""Tests for leaderboard generation functionality."""

import os
from pathlib import Path

import pandas as pd
import pytest

from cbioportal_mcp_qa.benchmark import regenerate_leaderboard


class TestLeaderboardGeneration:
    """Test leaderboard generation with various scenarios."""

    def test_leaderboard_with_no_results(self, temp_dir):
        """Test leaderboard generation when no results exist."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            regenerate_leaderboard()

            # Should not create leaderboard if no results
            leaderboard_path = temp_dir / "LEADERBOARD.md"
            assert not leaderboard_path.exists()

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_basic_structure(self, temp_dir):
        """Test basic leaderboard structure."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create minimal evaluation result
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            csv_content = """# Average correctness_score: 2.50,,,,,,,,
question,correctness_score,correctness_explanation
Q1,2,Explanation
Q2,3,Explanation
"""
            (eval_dir / "evaluation_20260210.csv").write_text(csv_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            assert leaderboard_path.exists()

            content = leaderboard_path.read_text()
            assert "# Benchmark Leaderboard" in content
            assert "|" in content  # Markdown table
            assert "Date" in content
            assert "Agent Type" in content

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_combines_evaluation_and_reproducibility(self, temp_dir):
        """Test that leaderboard combines both evaluation types."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            eval_dir = temp_dir / "results" / "agent-x" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            # Create evaluation CSV
            eval_csv = """# Average correctness_score: 2.75,,,,,,,,
# Average completeness_score: 3.00,,,,,,,,
question,correctness_score,completeness_score
Q1,3,3
Q2,2,3
Q3,3,3
"""
            (eval_dir / "evaluation_20260210.csv").write_text(eval_csv)

            # Create reproducibility CSV
            repro_csv = """# Average reproducibility_score: 2.85
question,reproducibility_score
Q1,3.0
Q2,2.7
"""
            (eval_dir / "reproducibility_20260210.csv").write_text(repro_csv)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Should include all score types
            assert "Correctness Score" in content
            assert "Completeness Score" in content
            assert "Reproducibility Score" in content

            # Check that values are present (allowing for different formatting)
            assert ("2.75" in content or "2.67" in content)  # Correctness average (allowing rounding)
            assert ("3.00" in content or "3" in content)  # Completeness average
            assert "2.85" in content  # Reproducibility average

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_multiple_dates_same_agent(self, temp_dir):
        """Test leaderboard with multiple runs of same agent."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # Create results for different dates
            for date in ["20260208", "20260209", "20260210"]:
                eval_dir = temp_dir / "results" / "agent-a" / date / "eval"
                eval_dir.mkdir(parents=True)

                csv_content = f"""# Average correctness_score: 2.50,,,,,,,,
question,correctness_score
Q1,2
Q2,3
"""
                (eval_dir / f"evaluation_{date}.csv").write_text(csv_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # All three dates should appear
            assert "20260208" in content
            assert "20260209" in content
            assert "20260210" in content

            # Most recent should appear first (descending order)
            lines = content.split('\n')
            date_positions = {
                "20260208": None,
                "20260209": None,
                "20260210": None
            }

            for i, line in enumerate(lines):
                for date in date_positions:
                    if date in line and date_positions[date] is None:
                        date_positions[date] = i

            assert date_positions["20260210"] < date_positions["20260209"]
            assert date_positions["20260209"] < date_positions["20260208"]

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_multiple_agents_multiple_dates(self, temp_dir):
        """Test leaderboard with multiple agents and dates."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            agents = ["agent-a", "agent-b", "agent-c"]
            dates = ["20260208", "20260210"]

            for agent in agents:
                for date in dates:
                    eval_dir = temp_dir / "results" / agent / date / "eval"
                    eval_dir.mkdir(parents=True)

                    csv_content = f"""# Average correctness_score: 2.50,,,,,,,,
question,correctness_score
Q1,2
Q2,3
"""
                    (eval_dir / f"evaluation_{date}.csv").write_text(csv_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # All agents should appear
            for agent in agents:
                assert agent in content

            # All dates should appear
            for date in dates:
                assert date in content

            # Should have multiple rows (agents x dates = 6 rows)
            table_rows = [line for line in content.split('\n') if line.startswith('|') and 'Date' not in line and '---' not in line]
            assert len(table_rows) == 6

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_score_formatting(self, temp_dir):
        """Test that scores are formatted to 2 decimal places."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            csv_content = """# Average correctness_score: 2.666666,,,,,,,,
# Average completeness_score: 2.333333,,,,,,,,
question,correctness_score,completeness_score
Q1,3,2
Q2,2,3
Q3,3,2
"""
            (eval_dir / "evaluation_20260210.csv").write_text(csv_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Scores should be formatted to 2 decimal places
            assert "2.67" in content  # 2.666666 rounded
            assert "2.33" in content  # 2.333333 rounded

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_handles_multiple_csvs(self, temp_dir):
        """Test that leaderboard uses the most recent CSV if multiple exist."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            # Create older CSV
            csv1_content = """# Average correctness_score: 1.50,,,,,,,,
question,correctness_score
Q1,1
Q2,2
"""
            csv1_path = eval_dir / "evaluation_20260210_old.csv"
            csv1_path.write_text(csv1_content)

            import time
            time.sleep(0.1)  # Ensure different modification times

            # Create newer CSV
            csv2_content = """# Average correctness_score: 2.50,,,,,,,,
question,correctness_score
Q1,2
Q2,3
"""
            csv2_path = eval_dir / "evaluation_20260210.csv"
            csv2_path.write_text(csv2_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Should use the newer CSV values (allow for trailing zero being dropped)
            assert ("2.50" in content or "2.5" in content)
            assert "1.50" not in content and "1.5" not in content

        finally:
            os.chdir(original_cwd)

    def test_leaderboard_sorted_score_columns(self, temp_dir):
        """Test that score columns are sorted alphabetically."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            eval_dir = temp_dir / "results" / "test-agent" / "20260210" / "eval"
            eval_dir.mkdir(parents=True)

            csv_content = """# Average correctness_score: 2.50,,,,,,,,
# Average faithfulness_score: 3.00,,,,,,,,
# Average completeness_score: 2.75,,,,,,,,
# Average conciseness_score: 2.00,,,,,,,,
question,correctness_score,faithfulness_score,completeness_score,conciseness_score
Q1,2,3,3,2
Q2,3,3,2,2
"""
            (eval_dir / "evaluation_20260210.csv").write_text(csv_content)

            regenerate_leaderboard()

            leaderboard_path = temp_dir / "LEADERBOARD.md"
            content = leaderboard_path.read_text()

            # Find header line
            header_line = [line for line in content.split('\n') if 'Correctness Score' in line][0]

            # Extract column order
            columns = [col.strip() for col in header_line.split('|') if col.strip()]

            # Score columns should be alphabetically sorted
            score_cols = [col for col in columns if 'Score' in col]
            assert score_cols == sorted(score_cols)

        finally:
            os.chdir(original_cwd)
