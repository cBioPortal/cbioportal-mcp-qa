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

## Reproducibility Evaluation

The reproducibility metric measures how consistently the model responds to the same question across multiple runs. This is inspired by the HELM (Holistic Evaluation of Language Models) robustness framework.

### How It Works

1. Each question is prompted N times (default: 3 when enabled)
2. All pairwise combinations of outputs are compared for semantic similarity
3. An LLM judge evaluates whether outputs convey the same information
4. The final score is the average of all pairwise consistency scores

### Scoring Rubric

- **3 (Highly Consistent)**: All runs produce semantically identical outputs. Numerical values match exactly. Conclusions are the same.
- **2 (Somewhat Consistent)**: Key facts overlap but some details differ. Minor variations in format or additional context.
- **1 (Inconsistent)**: Contradictory conclusions, different numerical answers, or substantial factual divergence.

### Usage

```bash
# Run benchmark with reproducibility testing (3 runs)
cbioportal-mcp-qa benchmark --agent-type mcp-clickhouse --reproducibility-runs 3

# Run with 5 runs for higher confidence
cbioportal-mcp-qa benchmark --agent-type mcp-clickhouse --reproducibility-runs 5
```

### Output

Results are saved to:
- `results/{agent_type}/{date}/reproducibility/run{N}/` - Individual run outputs
- `results/{agent_type}/{date}/eval/reproducibility_{date}.csv` - Reproducibility scores

The `reproducibility_score` is automatically included in LEADERBOARD.md.

### Cost Considerations

Running with `--reproducibility-runs N` will:
- Generate N times as many answers (N API calls per question)
- Run C(N,2) = N*(N-1)/2 pairwise comparisons per question

Example costs for 10 questions:
- N=3: 30 answer calls + 30 comparison calls = 60 total API calls
- N=5: 50 answer calls + 100 comparison calls = 150 total API calls
