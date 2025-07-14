"""CSV parser with question selection logic."""

import re
from pathlib import Path
from typing import List, Tuple

import pandas as pd


def parse_question_selection(selection: str) -> List[int]:
    """Parse question selection string into list of question numbers.
    
    Args:
        selection: String like "1-5", "1,3,5", or "all"
        
    Returns:
        List of question numbers
    """
    if selection.lower() == "all":
        return list(range(1, 103))  # 1-102
    
    questions = []
    
    # Split by comma and process each part
    parts = selection.split(",")
    for part in parts:
        part = part.strip()
        
        # Check if it's a range (e.g., "1-5")
        if "-" in part:
            start, end = part.split("-", 1)
            start, end = int(start.strip()), int(end.strip())
            questions.extend(range(start, end + 1))
        else:
            # Single number
            questions.append(int(part))
    
    # Remove duplicates and sort
    return sorted(list(set(questions)))


def load_questions(csv_path: Path, selected_questions: List[int]) -> List[Tuple[int, str, str]]:
    """Load questions from CSV file.
    
    Args:
        csv_path: Path to CSV file
        selected_questions: List of question numbers to load
        
    Returns:
        List of tuples (question_num, question_type, question_text)
    """
    df = pd.read_csv(csv_path)
    
    # Filter to selected questions
    filtered_df = df[df['#'].isin(selected_questions)]
    
    # Return as list of tuples
    questions = []
    for _, row in filtered_df.iterrows():
        questions.append((row['#'], row['Qustion Type'], row['Question']))
    
    return questions