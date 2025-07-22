"""Output manager for markdown file generation."""

from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

from .sql_logger import sql_query_logger


class OutputManager:
    """Manages output generation for QA results."""
    
    def __init__(self, output_dir: Path):
        """Initialize output manager.
        
        Args:
            output_dir: Directory to write output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def write_question_result(
        self, 
        question_num: int, 
        question_type: str, 
        question_text: str, 
        answer: str,
        include_sql: bool = False
    ) -> Path:
        """Write a question result to a markdown file.
        
        Args:
            question_num: Question number
            question_type: Type of question (e.g., "Basic/statistical")
            question_text: The original question
            answer: The answer from the LLM
            include_sql: Whether to include SQL queries in the output
            
        Returns:
            Path to the created file
        """
        filename = f"{question_num}.md"
        filepath = self.output_dir / filename
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Build content with optional SQL section
        content_parts = [
            f"# Question {question_num}",
            "",
            f"**Type:** {question_type}",
            "",
            f"**Question:** {question_text}",
            "",
            "**Answer:**",
            "",
            answer
        ]
        
        # Add SQL queries section if requested and available
        if include_sql and sql_query_logger.enabled:
            sql_markdown = sql_query_logger.get_queries_markdown()
            if sql_markdown:
                content_parts.extend(["", "---", "", sql_markdown])
        
        content_parts.extend(["", "---", "", f"*Generated on {timestamp}*"])
        
        content = "\n".join(content_parts)
        
        filepath.write_text(content, encoding="utf-8")
        return filepath