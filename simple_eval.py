#!/usr/bin/env python3

import os
import pandas as pd
import io
import click
from anthropic import Client
from dotenv import load_dotenv
import datetime

def evaluate_answer(client: Client, question: str, expected: str, 
                    output: str) -> pd.DataFrame:
    '''
    Evaluate the LLM output against the expected answer using the Anthropic API.
    Returns a DataFrame with the evaluation results.
    '''
    
    prompt = f"""
    Question: {question}
    Expected Answer: {expected}
    LLM Output: {output}
    Evaluate if the LLM Output matches the Expected Answer. Provide a score (0-10) and a brief explanation.
    Output the result in csv format with columns "Question", "Score" and "Explanation", for example:
    Question,Score,Explanation
    "How many states are there in the USA?",10,"The LLM Output correctly states that there are 50 states in the USA."
    """
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    df = pd.read_csv(io.StringIO(response.content[0].text))
    return df


@click.command()
@click.option('--input-csv', required=True, help='Path to input CSV file containing questions and expected answers.')
@click.option('--answers-dir', required=True, help='Directory containing LLM output files.')
@click.option('--output-dir', default='evaluation_results', help='Path to save evaluation results.')
def main(input_csv: str, answers_dir: str, output_dir: str):
    '''
    Main function to evaluate LLM outputs against expected answers.
    Reads the input CSV, processes each question-answer pair, and saves the evaluation results.
    input_csv: CSV file with columns "Question", "Expected Answer", "Claude Clickhouse MCP Answer"
    answers_dir: Directory where LLM output files are stored.
    output_dir: Directory to save the evaluation results as CSV files.
    '''
    load_dotenv()
    client = Client()
    data = pd.read_csv(input_csv)
    results = []

    for _, row in data.iterrows():
        if pd.notnull(row['Expected Answer']) and pd.notnull(row['Claude Clickhouse MCP Answer']):
            file_name = row['Claude Clickhouse MCP Answer']
            file_path = os.path.join(answers_dir, file_name)
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    llm_output = file.read()
                evaluation = evaluate_answer(client, row['Question'], row['Expected Answer'], llm_output)
                results.append(evaluation)
            else:
                print(f"File not found: {file_path}")

    if results:
        all_results = pd.concat(results)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = os.path.join(output_dir, f"evaluation_{timestamp}.csv")
        os.makedirs(output_dir, exist_ok=True)
        all_results.to_csv(output_csv, index=False)
        print(f"Evaluation results saved to {output_csv}")
    else:
        print("No results to save.")

if __name__ == '__main__':
    main()

