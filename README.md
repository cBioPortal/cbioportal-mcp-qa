# cBioPortal MCP QA

Process cBioPortal QA questions using PydanticAI with MCP ClickHouse integration.

## Setup

```bash
# Create Python 3.13 virtual environment
uv venv .venv --python 3.13
source .venv/bin/activate

# Install dependencies in editable mode (uses pyproject.toml + uv.lock)
uv sync --editable
```

## Configuration

Set required environment variables:

```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export CLICKHOUSE_HOST="your-clickhouse-host"
export CLICKHOUSE_USER="your-clickhouse-user"
export CLICKHOUSE_PASSWORD="your-clickhouse-password"
export CLICKHOUSE_DATABASE=your-cbioportal-database  # e.g., cgds_public_2025_06_24
```

### Open Telemetry with Arize Phoenix

Set the following environment variable to enable tracing:
```bash
PHOENIX_API_KEY='<your-api-key>'
PHOENIX_COLLECTOR_ENDPOINT='<your-collector-endpoint>'
```

You collector enpoint looks like `https://app.phoenix.arize.com/s/<USER/ORG>`. Don't add `/v1/traces` at the end.

Use `--enable-open-telemetry-tracing` option with `ask` or `batch` commands to trace the interactions.


## Usage

The tool provides two main modes: batch processing for multiple questions and single question mode for quick queries.

### Batch Processing

Process multiple questions from a CSV file:

```bash
# Process all questions
cbioportal-mcp-qa batch input/QA_pairs_20250714.csv

# Process specific questions
cbioportal-mcp-qa batch input/QA_pairs_20250714.csv --questions 1-5
cbioportal-mcp-qa batch input/QA_pairs_20250714.csv --questions 1,3,5

# Custom output directory with SQL query capture
cbioportal-mcp-qa batch input/QA_pairs_20250714.csv --questions 1-10 --output-dir results/ --include-sql
```

### Single Questions

Ask individual questions directly:

```bash
# Basic question (output to stdout)
cbioportal-mcp-qa ask "How many studies are there?"

# Save to file with markdown formatting
cbioportal-mcp-qa ask "What are the top 5 cancer types by sample count?" --output-file answer.md --format markdown

# Include SQL queries in output
cbioportal-mcp-qa ask "Show me mutation data for BRCA1" --format markdown --include-sql
```

## Features

- **Two operation modes**: Batch processing for CSV files and single question mode
- **Flexible question selection**: ranges (`1-5`), lists (`1,3,5`), or all questions (batch mode)
- **Multiple output formats**: Plain text or markdown formatting
- **SQL query capture**: Optional inclusion of executed SQL queries with `--include-sql`
- **Flexible output destinations**: stdout or file output
- **PydanticAI integration**: with MCP ClickHouse server for cBioPortal data access
- **Progress tracking**: real-time progress bars and status updates
- **Environment configuration**: CLI options and environment variables
- **Model flexibility**: Support for Anthropic Claude and Ollama models

## Output

**Batch Mode:**
Results are saved as individual markdown files in the `export/` directory (`1.md`, `2.md`, etc.) with:
- Question number, type, and original text
- AI-generated answer using cBioPortal data
- Optional SQL queries section (with `--include-sql`)
- cBioPortal cohort URLs for patient groups
- Timestamp and metadata

**Ask Mode:**
- **Plain format**: Direct answer text to stdout or file
- **Markdown format**: Structured markdown with question, answer, optional SQL queries, and timestamp

## Simple Evaluation Tool
The `simple_eval` tool evaluates LLM outputs against expected answers using the Anthropic API, generating CSV results with a score (0-10) and an explanation for each question.

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
- **correctness_score**: A score (0-5) indicating the factual accuracy of the LLM output.
- **correctness_explanation**: A brief explanation for the correctness score.
- **completeness_score**: A score (0-5) indicating how well the LLM output addresses the question.
- **completeness_explanation**: A brief explanation for the completeness score.
- **conciseness_score**: A score (0-5) indicating how concise the LLM output is.
- **conciseness_explanation**: A brief explanation for the conciseness score.
- **faithfulness_score**: A score (0-5) indicating whether the LLM output relies solely on the provided context.
- **faithfulness_explanation**: A brief explanation for the faithfulness score.

Additionally, the script calculates average scores for each category and appends them as comments at the top of the CSV file. These averages provide an overall evaluation summary.
