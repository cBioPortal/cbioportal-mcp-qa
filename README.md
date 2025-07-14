# cBioPortal MCP QA

Process cBioPortal QA questions using PydanticAI with MCP ClickHouse integration.

## Setup

```bash
# Create Python 3.13 virtual environment
uv venv .venv --python 3.13
source .venv/bin/activate

# Install dependencies
uv pip install -e .
```

## Configuration

Set required environment variables:

```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export CLICKHOUSE_HOST="your-clickhouse-host"
export CLICKHOUSE_USER="your-clickhouse-user"
export CLICKHOUSE_PASSWORD="your-clickhouse-password"
```

## Usage

```bash
# Process all questions
cbioportal-mcp-qa input/QA_pairs_20250714.csv

# Process specific questions
cbioportal-mcp-qa input/QA_pairs_20250714.csv --questions 1-5
cbioportal-mcp-qa input/QA_pairs_20250714.csv --questions 1,3,5

# Custom output directory
cbioportal-mcp-qa input/QA_pairs_20250714.csv --questions 1-10 --output-dir results/
```

## Features

- **Flexible question selection**: ranges (`1-5`), lists (`1,3,5`), or all questions
- **PydanticAI integration**: with MCP ClickHouse server for cBioPortal data access
- **Markdown output**: individual files for each question (`export/1.md`, `export/2.md`, etc.)
- **Progress tracking**: real-time progress bars and status updates
- **Environment configuration**: CLI options and environment variables

## Output

Results are saved as markdown files in the `export/` directory with:
- Question number, type, and original text
- AI-generated answer using cBioPortal data
- cBioPortal cohort URLs for patient groups
- Timestamp and metadata