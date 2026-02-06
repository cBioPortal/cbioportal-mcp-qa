# Evaluation

## Simple Evaluation Tool
The `simple_eval` tool evaluates LLM outputs against expected answers using the Anthropic API, generating CSV results with scores (1-3) and an explanation for each question.

### Command Syntax
```bash
python simple_eval.py --input-csv <input_csv_path> --answers-dir <answers_directory> [--output-dir <output_directory>]
```

### Options
- `--input-csv`: Path to the input CSV file containing questions and expected answers.
- `--answers-dir`: Directory containing the LLM output files.
- `--output-dir`: (Optional) Directory to save the evaluation results. Defaults to `evaluation_results`.

### Input CSV Format
The input CSV file should have the following columns:
- `Question`: The question to evaluate.
- `Expected Answer`: The expected answer for the question.
- `Claude Clickhouse MCP Answer`: The filename of the LLM output stored in the `answers-dir`.

### Output

The `simple_eval.py` script generates a CSV file with a timestamped filename in the specified output directory. The CSV contains the following columns:

- **question**: The original question being evaluated.
- **correctness_score**: A score (1-3) indicating the factual accuracy of the LLM output.
- **correctness_explanation**: A brief explanation for the correctness score.
- **completeness_score**: A score (1-3) indicating how well the LLM output addresses the question.
- **completeness_explanation**: A brief explanation for the completeness score.
- **conciseness_score**: A score (1-3) indicating how concise the LLM output is.
- **conciseness_explanation**: A brief explanation for the conciseness score.
- **faithfulness_score**: A score (1-3) indicating whether the LLM output relies solely on the provided context.
- **faithfulness_explanation**: A brief explanation for the faithfulness score.

Additionally, the script calculates average scores for each category and appends them as comments at the top of the CSV file. These averages provide an overall evaluation summary.
