#!/usr/bin/env python3

import os
import click
import datetime
import json
import time
import pandas as pd
from anthropic import Client
from dotenv import load_dotenv


def evaluate(client: Client, question: str, expected: str,
             output: str) -> str:
    '''
    Evaluate the LLM output against the expected answer using multiple criteria.
        client: Initialized Anthropic Client.
        question: The user's question.
        expected: The expected correct answer.
        output: The LLM's output to be evaluated.
    Returns a JSON object with scores and explanations for each criterion.
    '''

    prompt = f'''
    Question: {question}
    Context/Source: cbioportal database
    Expected Answer: {expected}
    LLM Output: {output}

    Instructions:
    Evaluate the LLM Output based on the following criteria. Provide a score from 0 to 5 for each criterion and a brief explanation.

    - **Correctness (0-5)**: Is the information in the LLM Output factually accurate? Score 5 for perfectly accurate, 0 for completely incorrect.
    - **Completeness (0-5)**: Does the LLM Output fully address the user's question? Score 5 for a complete answer, 0 for a missing answer.
    - **Conciseness (0-5)**: Is the LLM Output direct and to the point, avoiding unnecessary details? Score 5 for perfectly concise, 0 for excessively verbose. Ignore the included SQL queries and timestamops when evaluating conciseness.
    - **Faithfulness (0-5)**: Does the LLM Output rely only on the provided Context/Source? Score 5 if all information is traceable to the source, 0 if it contains hallucinations or outside knowledge.

    Provide your final output in a structured format, as a JSON object with the following keys:
    - "question": The original question.
    - "correctness_score": The score for correctness.
    - "correctness_explanation": The explanation for the correctness score.
    - "completeness_score": The score for completeness.
    - "completeness_explanation": The explanation for the completeness score.
    - "conciseness_score": The score for conciseness.
    - "conciseness_explanation": The explanation for the conciseness score.
    - "faithfulness_score": The score for faithfulness.
    - "faithfulness_explanation": The explanation for the faithfulness score.

    Example Output (JSON):
    ```json
    {{
    "question": "What is the mutational frequency of BRAF in breast cancer?",
    "correctness_score": 5,
    "correctness_explanation": "The output correctly states the mutational frequency as 5.2%.",
    "completeness_score": 5,
    "completeness_explanation": "The answer fully addresses the question by providing the frequency and the cancer type.",
    "conciseness_score": 4,
    "conciseness_explanation": "The output is mostly concise but includes a minor, unnecessary detail about a related gene.",
    "faithfulness_score": 5,
    "faithfulness_explanation": "The answer is based solely on the provided context, with no external information."
    }}
    ```
    '''

    max_retries = 3
    for attempt in range(max_retries):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.replace(
            "```json", "").replace("```", "").strip()
        try:
            response_json = json.loads(response_text)
            return response_json
        except json.JSONDecodeError as e:
            print(
                f"JSON decode error: {e}. Retrying ({attempt+1}/{max_retries})...")
            time.sleep(2)
            if attempt == max_retries - 1:
                print("Failed to parse JSON after retries. Returning raw response.")
                return {"error": "Invalid JSON", "raw_response": response_text}


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

    # Iterate over each row in the input CSV and evaluate the LLM output
    for _, row in data.iterrows():
        if pd.notnull(row['Expected Answer']) and pd.notnull(row['Claude Clickhouse MCP Answer']):
            file_name = row['Claude Clickhouse MCP Answer']
            file_path = os.path.join(answers_dir, file_name)
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    llm_output = file.read()
                response = evaluate(client, row['Question'],
                                    row['Expected Answer'], llm_output)
                print(
                    f"\nEvaluation response for question '{row['Question']}':\n{response}")
                df = pd.DataFrame([response])
                results.append(df)
            else:
                print(f"File not found: {file_path}")

    # Save all results to a single CSV file with timestamp
    if results:
        all_results = pd.concat(results)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = os.path.join(output_dir, f"evaluation_{timestamp}.csv")
        os.makedirs(output_dir, exist_ok=True)
        all_results.to_csv(output_csv, index=False)
        print(f"\nEvaluation results saved to {output_csv}")
    else:
        print("\nNo results to save.")

    # Calculate average scores per category
    if results:
        numeric_cols = [
            "correctness_score",
            "completeness_score",
            "conciseness_score",
            "faithfulness_score"
        ]
        averages = all_results[numeric_cols].astype(float).mean()
        print("\nAverage scores per category:")
        for col in numeric_cols:
            print(f"Average {col}: {averages[col]:.2f}")

        # Add average scores as a comment at the top of the CSV file
        comment_lines = [
            f"# Average {col}: {averages[col]:.2f}" for col in numeric_cols]
        comment_block = "\n".join(comment_lines) + "\n"
        with open(output_csv, 'r') as f:
            csv_content = f.read()
        with open(output_csv, 'w') as f:
            f.write(comment_block)
            f.write(csv_content)


if __name__ == '__main__':
    main()

