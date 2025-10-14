#!/usr/bin/env python3

from datetime import datetime
import os
import json
import click
from anthropic import Client
from dotenv import load_dotenv
from openai import responses


def evaluate_steps(client: Client, question: str, expected: str,
                   output: str) -> str:
    '''
    Evaluate the SQL queries in the LLM output against the expected steps.
    Returns a JSON response with missing steps, extra steps, and scores for completeness, conciseness, and correctness.
    '''

    prompt = '''
    Question: {question}
    Context/Source: cbioportal database
    Expected Steps: {expected}
    LLM Output: {output}

    Instructions:
    Evaluate the series of SQL queries in the LLM Output against the Expected Steps. Any steps that require calculations or transformations should be reflected in the SQL queries, otherwise they should be marked as missing.
    Provide a JSON response with the following fields:
    {{
        "missing_steps": [list of missing steps and corresponding step number, if any (each missing step should be listed individually)],
        "extra_steps": [list of extra steps and corresponding query number, if any (each extra step should be listed individually)],
        "steps_to_queries_mapping": {{"step_number": "corresponding_query_number", ...}},
        "completeness": Provide a score of 1 to 3. Score 3 when all expected steps are present, 2 when few steps are missing, and 1 when many steps are missing.
        "conciseness": Provide a score of 1 to 3. Score 3 when all queries correspond directly to expected steps, 2 when there are a few extra queries, and 1 when there are many extra queries.
        "correctness": Provide a score of 1 to 3. Score 3 when the overall logic of the queries is consistent with the expected results, 2 when there are some logical errors, and 1 when there are significant logical errors.
        "comments": "Brief explanation of the evaluation"
    }}
    Ensure the JSON is properly formatted and enclosed within triple backticks, as shown in this example output (JSON):
    ```json
    {{
        "missing_steps": ["Step 2: Filter by cancer type", "Step 4: Calculate average mutation frequency"],
        "extra_steps": ["Query 3: Unnecessary join with patients table", "Query 4: Additional breakdown of mutation types"],
        "steps_to_queries_mapping": {{"1": "1", "3": "2,5"}},
        "completeness": 0,
        "conciseness": 0,
        "correctness": 1,
        "comments": "The LLM output correctly follows the expected steps but misses filtering by cancer type and includes an unnecessary join."
    }}
    '''

    prompt = prompt.format(question=question, expected=expected, output=output)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = json.loads(response.content[0].text.replace(
        "```json", "").replace("```", "").strip())

    return response_text


@click.command()
@click.option('--input-rubrics', required=True,
              help='JSON file containing questions and expected steps.')
@click.option('--answers-dir', required=True,
              help='Directory containing LLM output files with SQL queries.')
@click.option('--output-dir', default='evaluation_results',
              help='Path to save evaluation results.')
def main(input_rubrics: str, answers_dir: str, output_dir: str):
    '''
    Main function to evaluate LLM outputs against expected steps.
    Reads the input JSON, processes each question-answer pair, and saves the evaluation results.
        input_rubrics: JSON file with fields "question" and "answer_instructions"
        answers_dir: Directory containing LLM output files named as "<question_number>.md"
        output_dir: Directory to save evaluation results
    '''

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    load_dotenv()
    client = Client()

    with open(input_rubrics, 'r') as f:
        answers = json.load(f)
    print(f"Loaded {len(answers)} questions from {input_rubrics}")

    responses = dict()
    for idx, ans in answers.items():

        steps = ans.get('answer_instructions')
        if steps:
            detailed = steps.get('detailed')
            brief = steps.get('brief')
        else:
            print(f"\nNo steps found for question #{idx}")
            continue

        file_path = os.path.join(answers_dir, f'{idx}.md')
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                llm_output = file.read()

        print(f"\nEvaluating steps for question #{idx}")

        responses[idx] = dict()
        responses[idx]['question'] = ans.get('question')

        if brief:
            response_brief = evaluate_steps(client, ans.get('question'),
                                            brief, llm_output)
            responses[idx]['response_brief'] = response_brief
        if detailed:
            response_detailed = evaluate_steps(client, ans.get('question'),
                                               detailed, llm_output)
            responses[idx]['response_detailed'] = response_detailed

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_json = os.path.join(output_dir, f"{timestamp}_steps_eval.json")

    with open(output_json, 'w') as json_file:
        json.dump(responses, json_file, indent=4)
    print(f"\nEvaluation results saved to {output_json}\n")

    # Calculate and save average scores
    brief_completeness_scores = []
    brief_conciseness_scores = []
    brief_correctness_scores = []

    detailed_completeness_scores = []
    detailed_conciseness_scores = []
    detailed_correctness_scores = []

    for resp in responses.values():
        brief = resp.get('response_brief', {})
        if brief:
            brief_completeness_scores.append(brief.get('completeness', 0))
            brief_conciseness_scores.append(brief.get('conciseness', 0))
            brief_correctness_scores.append(brief.get('correctness', 0))

        detailed = resp.get('response_detailed', {})
        if detailed:
            detailed_completeness_scores.append(
                detailed.get('completeness', 0))
            detailed_conciseness_scores.append(detailed.get('conciseness', 0))
            detailed_correctness_scores.append(detailed.get('correctness', 0))

    def average(scores):
        return round(sum(scores) / len(scores), 2) if scores else 0

    avg_scores = [
        f"Average completeness (brief): {average(brief_completeness_scores)} for {len(brief_completeness_scores)} questions",
        f"Average conciseness (brief): {average(brief_conciseness_scores)} for {len(brief_conciseness_scores)} questions",
        f"Average correctness (brief): {average(brief_correctness_scores)} for {len(brief_correctness_scores)} questions",
        f"Average completeness (detailed): {average(detailed_completeness_scores)} for {len(detailed_completeness_scores)} questions",
        f"Average conciseness (detailed): {average(detailed_conciseness_scores)} for {len(detailed_conciseness_scores)} questions",
        f"Average correctness (detailed): {average(detailed_correctness_scores)} for {len(detailed_correctness_scores)} questions"
    ]

    for line in avg_scores:
        print(line)

    output_file = os.path.join(output_dir,
                               f"{timestamp}_steps_eval_average_scores.txt")

    with open(output_file, "w") as f:
        for line in avg_scores:
            f.write(line + "\n")
    print(f"\nAverage scores saved to {output_file}")


if __name__ == '__main__':
    main()
