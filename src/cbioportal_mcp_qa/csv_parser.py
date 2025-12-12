"""CSV parser with question selection logic."""

import re
from pathlib import Path
from typing import List, Tuple

import pandas as pd


def get_max_questions(csv_path: Path) -> int:
    """Get the maximum number of questions in a CSV file.
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        Maximum question number available
    """
    sep = '\t' if str(csv_path).endswith('.tsv') else ','
    df = pd.read_csv(csv_path, sep=sep)
    
    if '#' in df.columns:
        # Use the maximum value in the '#' column, ignoring NaN values
        return int(df['#'].dropna().max())
    else:
        # Use the number of data rows (excluding header)
        return len(df)


def parse_question_selection(selection: str, csv_path: Path) -> List[int]:
    """Parse question selection string into list of question numbers.
    
    Args:
        selection: String like "1-5", "1,3,5", or "all"
        csv_path: Path to CSV file (to determine max questions for "all")
        
    Returns:
        List of question numbers
    """
    if selection.lower() == "all":
        max_questions = get_max_questions(csv_path)
        return list(range(1, max_questions + 1))
    
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
    sep = '\t' if str(csv_path).endswith('.tsv') else ','
    df = pd.read_csv(csv_path, sep=sep)
    
    # Check if '#' column exists, if not use row numbers (1-based)
    if '#' in df.columns:
        # Use existing '#' column
        filtered_df = df[df['#'].isin(selected_questions)]
        questions = []
        for _, row in filtered_df.iterrows():
            questions.append((int(row['#']), row['Question Type'], row['Question']))
    else:
        # Use row numbers as question numbers (1-based indexing)
        df['question_num'] = range(1, len(df) + 1)
        filtered_df = df[df['question_num'].isin(selected_questions)]
        questions = []
        for _, row in filtered_df.iterrows():
            questions.append((int(row['question_num']), row['Question Type'], row['Question']))
    
    return questions
