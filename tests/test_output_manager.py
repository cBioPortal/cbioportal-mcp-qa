"""Tests for OutputManager functionality."""

import pytest
from pathlib import Path

from cbioportal_mcp_qa.output_manager import OutputManager


class TestOutputManager:
    """Test OutputManager class."""

    def test_init_creates_directory(self, temp_dir):
        """Test that OutputManager creates output directory on init."""
        output_dir = temp_dir / "test_output"
        assert not output_dir.exists()

        manager = OutputManager(output_dir)
        assert output_dir.exists()
        assert manager.output_dir == output_dir

    def test_write_question_result_basic(self, temp_dir):
        """Test writing a basic question result."""
        manager = OutputManager(temp_dir)
        filepath = manager.write_question_result(
            question_num=1,
            question_type="Data Discovery",
            question_text="How many studies are in cBioPortal?",
            answer="There are 492 studies."
        )

        assert filepath.exists()
        assert filepath.name == "1.md"

        content = filepath.read_text()
        assert "# Question 1" in content
        assert "**Type:** Data Discovery" in content
        assert "**Question:** How many studies are in cBioPortal?" in content
        assert "**Answer:**" in content
        assert "There are 492 studies." in content

    def test_write_question_result_with_model_info(self, temp_dir):
        """Test writing question result with model information."""
        manager = OutputManager(temp_dir)
        model_info = {
            "model": "claude-sonnet-4-5-20250929",
            "use_ollama": False,
            "max_tokens": 4096
        }

        filepath = manager.write_question_result(
            question_num=2,
            question_type="Clinical Data",
            question_text="Test question?",
            answer="Test answer.",
            model_info=model_info
        )

        content = filepath.read_text()
        assert "## Model Information" in content
        assert "**Model:** claude-sonnet-4-5-20250929" in content
        assert "**Provider:** Anthropic" in content
        assert "**Max Tokens:** 4096" in content

    def test_write_question_result_with_ollama(self, temp_dir):
        """Test writing question result with Ollama provider."""
        manager = OutputManager(temp_dir)
        model_info = {
            "model": "llama3",
            "use_ollama": True,
            "ollama_base_url": "http://localhost:11434",
            "max_tokens": 2048
        }

        filepath = manager.write_question_result(
            question_num=3,
            question_type="Basic Query",
            question_text="What is X?",
            answer="X is Y.",
            model_info=model_info
        )

        content = filepath.read_text()
        assert "**Provider:** Ollama (http://localhost:11434)" in content

    def test_write_question_result_includes_timestamp(self, temp_dir):
        """Test that written files include timestamp."""
        manager = OutputManager(temp_dir)
        filepath = manager.write_question_result(
            question_num=1,
            question_type="Test",
            question_text="Test?",
            answer="Answer."
        )

        content = filepath.read_text()
        assert "Generated on" in content

    def test_write_multiple_questions(self, temp_dir):
        """Test writing multiple question results."""
        manager = OutputManager(temp_dir)

        for i in range(1, 4):
            filepath = manager.write_question_result(
                question_num=i,
                question_type="Test Type",
                question_text=f"Question {i}?",
                answer=f"Answer {i}."
            )
            assert filepath.exists()
            assert filepath.name == f"{i}.md"

        # Verify all files exist
        assert len(list(temp_dir.glob("*.md"))) == 3

    def test_write_question_result_returns_path(self, temp_dir):
        """Test that write_question_result returns the correct Path."""
        manager = OutputManager(temp_dir)
        filepath = manager.write_question_result(
            question_num=5,
            question_type="Test",
            question_text="Q?",
            answer="A."
        )

        assert isinstance(filepath, Path)
        assert filepath.parent == temp_dir
        assert filepath.name == "5.md"

    def test_write_question_result_with_include_sql_false(self, temp_dir):
        """Test writing without SQL queries when include_sql is False."""
        manager = OutputManager(temp_dir)
        filepath = manager.write_question_result(
            question_num=1,
            question_type="Test",
            question_text="Q?",
            answer="A.",
            include_sql=False
        )

        content = filepath.read_text()
        # Should not have SQL section (note: actual SQL would come from sql_logger)
        assert "## SQL Queries" not in content

    def test_write_question_result_encoding(self, temp_dir):
        """Test that special characters are handled correctly."""
        manager = OutputManager(temp_dir)
        filepath = manager.write_question_result(
            question_num=1,
            question_type="Test",
            question_text="What about special chars: é, ñ, 中文?",
            answer="Answer with unicode: μ, Σ, Ω"
        )

        content = filepath.read_text(encoding="utf-8")
        assert "é, ñ, 中文" in content
        assert "μ, Σ, Ω" in content
