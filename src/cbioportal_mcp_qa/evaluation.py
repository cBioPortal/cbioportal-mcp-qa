import datetime
import json
import os
import time
import re
import pandas as pd
from anthropic import Anthropic, AnthropicBedrock
from dotenv import load_dotenv


def get_anthropic_client(use_bedrock: bool = False, aws_profile: str = None):
    """Get the appropriate Anthropic client based on configuration.

    Args:
        use_bedrock: Whether to use AWS Bedrock instead of Anthropic API
        aws_profile: AWS profile name for Bedrock authentication

    Returns:
        Anthropic or AnthropicBedrock client
    """
    if use_bedrock:
        import boto3
        if aws_profile:
            session = boto3.Session(profile_name=aws_profile)
            credentials = session.get_credentials()
            return AnthropicBedrock(
                aws_access_key=credentials.access_key,
                aws_secret_key=credentials.secret_key,
                aws_session_token=credentials.token,
                aws_region=session.region_name or "us-east-1",
            )
        else:
            # Use default AWS credential chain
            return AnthropicBedrock()
    else:
        return Anthropic()


def evaluate(client, question: str, expected: str,
             output: str, use_bedrock: bool = False) -> str:
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
    Evaluate the LLM Output based on the following criteria. Provide a score from 1 to 3 for each criterion and a brief explanation.

    - **Correctness (1-3)**: Is the information in the LLM Output factually accurate? Score 3 for perfectly accurate, 2 for partially accurate, 1 for completely incorrect.
    - **Completeness (1-3)**: Does the LLM Output fully address the user's question? Score 3 for a complete answer, 2 for a partially complete answer, 1 for a missing answer.
    - **Conciseness (1-3)**: Is the LLM Output direct and to the point, avoiding unnecessary details? Score 3 for perfectly concise, 2 for somewhat verbose, 1 for excessively verbose. Ignore the included SQL queries and timestamops when evaluating conciseness.
    - **Faithfulness (1-3)**: Does the LLM Output rely only on the provided Context/Source? Score 3 if all information is traceable to the source, 2 for some reliance on external information, 1 if it contains hallucinations or outside knowledge.

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
    "correctness_score": 3,
    "correctness_explanation": "The output correctly states the mutational frequency as 5.2%.",
    "completeness_score": 3,
    "completeness_explanation": "The answer fully addresses the question by providing the frequency and the cancer type.",
    "conciseness_score": 2,
    "conciseness_explanation": "The output is mostly concise but includes a minor, unnecessary detail about a related gene.",
    "faithfulness_score": 3,
    "faithfulness_explanation": "The answer is based solely on the provided context, with no external information."
    }}
    ```
    '''

    # Select model based on client type
    if use_bedrock:
        model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    else:
        model = "claude-sonnet-4-5-20250929"

    max_retries = 3
    for attempt in range(max_retries):
        response = client.messages.create(
            model=model,
            max_tokens=500,
            temperature=0.0,
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


def extract_tokens(llm_output: str) -> tuple[int | None, int | None]:
    m_in = re.search(r"^\s*-\s*\*\*input_tokens\*\*:\s*(\d+)\s*$", llm_output, re.M)
    m_out = re.search(r"^\s*-\s*\*\*output_tokens\*\*:\s*(\d+)\s*$", llm_output, re.M)
    input_tokens = int(m_in.group(1)) if m_in else None
    output_tokens = int(m_out.group(1)) if m_out else None
    return input_tokens, output_tokens


def extract_response_time_seconds(llm_output: str) -> float | None:
    m_time = re.search(
        r"^\s*-\s*\*\*response_time_seconds\*\*:\s*([0-9]*\.?[0-9]+)\s*$",
        llm_output,
        re.M,
    )
    return float(m_time.group(1)) if m_time else None


def run_evaluation_logic(input_csv: str, answers_dir: str, output_dir: str, answer_column: str,
                         use_bedrock: bool = False, aws_profile: str = None) -> dict:
    '''
    Programmatic entry point for evaluation.
    Returns a dictionary of average scores.

    Args:
        input_csv: Path to input CSV with questions and expected answers
        answers_dir: Directory containing generated answer files
        output_dir: Directory to save evaluation results
        answer_column: Column name containing expected answers
        use_bedrock: Whether to use AWS Bedrock instead of Anthropic API
        aws_profile: AWS profile name for Bedrock authentication
    '''
    load_dotenv()
    client = get_anthropic_client(use_bedrock=use_bedrock, aws_profile=aws_profile)
    sep = '\t' if input_csv.endswith('.tsv') else ','
    data = pd.read_csv(input_csv, sep=sep)
    results = []

    # assert we have answer column (which is used as the EXPECTED answer column here)
    if answer_column not in data.columns:
        print(f"Warning: Expected answer column '{answer_column}' not found in CSV. Available: {data.columns}")
        return {}

    # Iterate over each row in the input CSV and evaluate the LLM output
    for qidx, (_, row) in enumerate(data.iterrows(), start=1):

        # check to make sure we have an answer for this question
        # We assume filenames are 1.md, 2.md, etc. corresponding to row index + 1 or Question ID
        # Since input CSV usually has explicit IDs, relying on 1-based index is risky if rows are skipped.
        # But for benchmark on base-set, we assume row 1 = Question 1.
        
        # Try to find Question ID if available, else index
        if 'Question ID' in row:
             qid = row['Question ID']
        else:
             qid = qidx
             
        answer_file_path = os.path.join(answers_dir, f'{qid}.md')
        
        if not os.path.isfile(answer_file_path):
            # Fallback to just index if ID didn't work
            answer_file_path = os.path.join(answers_dir, f'{qidx}.md')
            if not os.path.isfile(answer_file_path):
                continue

        # get the answer
        with open(answer_file_path, 'r') as file:
            llm_output = file.read()
            
        expected_val = row[answer_column]
        if pd.isnull(expected_val):
            continue
            
        response = evaluate(client, row['Question'],
                            str(expected_val), llm_output, use_bedrock=use_bedrock)

        input_tokens, output_tokens = extract_tokens(llm_output)
        response_time_seconds = extract_response_time_seconds(llm_output)
        response['input_tokens'] = input_tokens
        response['output_tokens'] = output_tokens
        response['response_time_seconds'] = response_time_seconds

        print(
            f"\nEvaluation response for question '{row['Question']}':\n{response}")
        df = pd.DataFrame([response])
        results.append(df)

    averages = {}
    
    # Save all results to a single CSV file with timestamp
    if results:
        all_results = pd.concat(results)
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        output_csv = os.path.join(output_dir, f"evaluation_{timestamp}.csv")
        os.makedirs(output_dir, exist_ok=True)
        all_results.to_csv(output_csv, index=False)
        print(f"\nEvaluation results saved to {output_csv}")
        
        # Calculate averages for all columns ending with '_score'
        numeric_cols = [col for col in all_results.columns if col.endswith('_score')]
        
        # Calculate averages
        avg_series = all_results[numeric_cols].astype(float).mean()
        averages = avg_series.to_dict()
        
        print("\nAverage scores per category:")
        for col in numeric_cols:
            print(f"Average {col}: {averages[col]:.2f}")

        # Add average scores as a comment at the top of the CSV file
        comment_lines = [
            f"# Average {col}: {averages[col]:.2f},,,,,,,," for col in numeric_cols]
        comment_block = "\n".join(comment_lines) + "\n"
        with open(output_csv, 'r') as f:
            csv_content = f.read()
        with open(output_csv, 'w') as f:
            f.write(comment_block)
            f.write(csv_content)
    else:
        print("\nNo results to save.")
        
    return averages
