"""Output manager for markdown file generation."""

from datetime import datetime
from pathlib import Path
from typing import Tuple


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
        answer: str
    ) -> Path:
        """Write a question result to a markdown file.
        
        Args:
            question_num: Question number
            question_type: Type of question (e.g., "Basic/statistical")
            question_text: The original question
            answer: The answer from the LLM
            
        Returns:
            Path to the created file
        """
        filename = f"{question_num}.md"
        filepath = self.output_dir / filename
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        content = f"""# Question {question_num}

**Type:** {question_type}

**Question:** {question_text}

**Answer:**

{answer}

---

*Generated on {timestamp}*
"""
        
        filepath.write_text(content, encoding="utf-8")
        return filepath