"""Output manager for markdown file generation."""

from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional


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
        include_sql: bool = False,
        model_info: Optional[dict] = None
    ) -> Path:
        """Write a question result to a markdown file.
        
        Args:
            question_num: Question number
            question_type: Type of question (e.g., "Basic/statistical")
            question_text: The original question
            answer: The answer from the LLM
            include_sql: Whether to include SQL queries in the output
            model_info: Dict with model and parameter information
            
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

        # Add model information section
        if model_info:
            content_parts.extend(["", "---", "", "## Model Information"])
            for key, value in model_info.items():
                if key != "usage":
                    content_parts.append(f"- **{key}**: {value}")

            if "usage" in model_info:
                usage = model_info["usage"]
                content_parts.append("")
                content_parts.append("### Usage")
                for usage_key, usage_value in usage.items():
                    content_parts.append(f"- **{usage_key}**: {usage_value}")
        
        content_parts.extend(["", "---", "", f"*Generated on {timestamp}*"])
        
        content = "\n".join(content_parts)
        
        filepath.write_text(content, encoding="utf-8")
        return filepath