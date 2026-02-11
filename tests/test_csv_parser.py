"""Tests for CSV parsing functionality."""

from cbioportal_mcp_qa.csv_parser import (
    parse_question_selection,
    load_questions,
    get_max_questions
)


class TestParseQuestionSelection:
    """Test question selection parsing."""

    def test_parse_all(self, sample_csv_path):
        """Test parsing 'all' returns all questions."""
        questions = parse_question_selection("all", sample_csv_path)
        assert questions == [1, 2, 3]

    def test_parse_single_number(self, sample_csv_path):
        """Test parsing a single question number."""
        questions = parse_question_selection("2", sample_csv_path)
        assert questions == [2]

    def test_parse_comma_separated(self, sample_csv_path):
        """Test parsing comma-separated question numbers."""
        questions = parse_question_selection("1,3", sample_csv_path)
        assert questions == [1, 3]

    def test_parse_range(self, sample_csv_path):
        """Test parsing a range of questions."""
        questions = parse_question_selection("1-3", sample_csv_path)
        assert questions == [1, 2, 3]

    def test_parse_mixed_format(self, sample_csv_path):
        """Test parsing mixed comma and range format."""
        questions = parse_question_selection("1,3-5,7", sample_csv_path)
        assert questions == [1, 3, 4, 5, 7]

    def test_parse_removes_duplicates(self, sample_csv_path):
        """Test that duplicate question numbers are removed."""
        questions = parse_question_selection("1,2,1,3,2", sample_csv_path)
        assert questions == [1, 2, 3]

    def test_parse_returns_sorted(self, sample_csv_path):
        """Test that results are sorted."""
        questions = parse_question_selection("3,1,2", sample_csv_path)
        assert questions == [1, 2, 3]


class TestGetMaxQuestions:
    """Test getting maximum question count."""

    def test_get_max_with_hash_column(self, sample_csv_with_question_id):
        """Test getting max questions from CSV with '#' column."""
        max_q = get_max_questions(sample_csv_with_question_id)
        assert max_q == 3

    def test_get_max_without_hash_column(self, sample_csv_path):
        """Test getting max questions from CSV without '#' column."""
        max_q = get_max_questions(sample_csv_path)
        assert max_q == 3


class TestLoadQuestions:
    """Test loading questions from CSV."""

    def test_load_all_questions(self, sample_csv_path):
        """Test loading all questions."""
        questions = load_questions(sample_csv_path, [1, 2, 3])
        assert len(questions) == 3
        assert questions[0][0] == 1  # Question number
        assert questions[0][1] == "Data Discovery"  # Question type
        assert "How many studies" in questions[0][2]  # Question text

    def test_load_subset_questions(self, sample_csv_path):
        """Test loading a subset of questions."""
        questions = load_questions(sample_csv_path, [1, 3])
        assert len(questions) == 2
        assert questions[0][0] == 1
        assert questions[1][0] == 3

    def test_load_questions_with_id_column(self, sample_csv_with_question_id):
        """Test loading questions from CSV with '#' column."""
        questions = load_questions(sample_csv_with_question_id, [1, 2])
        assert len(questions) == 2
        assert questions[0][0] == 1
        assert questions[1][0] == 2
        assert questions[0][1] == "Data Discovery"

    def test_load_questions_preserves_order(self, sample_csv_path):
        """Test that loaded questions maintain CSV order."""
        questions = load_questions(sample_csv_path, [1, 2, 3])
        assert [q[0] for q in questions] == [1, 2, 3]

    def test_load_questions_with_special_characters(self, sample_csv_path):
        """Test loading questions with special characters in text."""
        questions = load_questions(sample_csv_path, [3])
        # Question 3 has quoted content with percentages
        assert "%" in questions[0][2] or "top 5" in questions[0][2].lower()
