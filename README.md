# cBioPortal MCP QA & Benchmarking

This repository serves as the benchmarking system for efforts to provide an agentic interface to cBioPortal.org. It is designed to evaluate various "agents" (like MCP servers or standalone APIs) that answer questions about cancer genomics data.

**🏆 [View the Leaderboard](LEADERBOARD.md)** to see current benchmark results.

## Overview

The system provides a modular CLI to:
1.  **Ask** single questions to different agents.
2.  **Batch** process a set of questions.
3.  **Benchmark** agents against a gold-standard dataset, automatically evaluating their accuracy using an LLM judge.

## Supported Agents

The system currently supports the following agent types via the `--agent-type` flag:

1.  `mcp-clickhouse`: The original Model Context Protocol (MCP) agent connected to a ClickHouse database.
2.  `cbio-agent-null`: A baseline/testing agent (or a specific implementation hosted at a URL).

## Setup

```bash
# Create Python 3.13 virtual environment
uv venv .venv --python 3.13
source .venv/bin/activate

# Install dependencies in editable mode
uv sync --editable
```

## Configuration

Create a `.env` file or export the following environment variables:

**General:**
*   `ANTHROPIC_API_KEY`: Required for the LLM judge (evaluation) and the `mcp-clickhouse` agent.

**For `cbio-agent-null`:**
*   `CBIO_NULL_AGENT_URL`: URL of the agent API (e.g., `http://localhost:8000`).

**For `mcp-clickhouse`:**
*   `CLICKHOUSE_HOST`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`: Connection details.

**Optional (Tracing):**
*   `PHOENIX_API_KEY`: For Arize Phoenix tracing.
*   `PHOENIX_COLLECTOR_ENDPOINT`: Tracing endpoint.

## Benchmarking (Primary Workflow)

The `benchmark` command is the main way to evaluate an agent. It automates generation, evaluation, and leaderboard updates.

```bash
# Run benchmark for the null agent
cbioportal-mcp-qa benchmark --agent-type cbio-agent-null --questions 1-5

# Run benchmark for the MCP agent
cbioportal-mcp-qa benchmark --agent-type mcp-clickhouse
```

**What happens:**
1.  Questions are loaded from `input/autosync-public.csv`.
2.  The specified agent generates answers.
3.  Answers are saved to `results/{agent_type}/{YYYYMMDD}/answers/`.
4.  `simple_eval.py` evaluates the answers against the expected output (using `Navbot Expected Link` as the ground truth).
5.  Results are saved to `results/{agent_type}/{YYYYMMDD}/eval/`.
6.  `LEADERBOARD.md` is updated with the latest scores.

## Manual Usage (CLI Reference)

You can also run individual components manually.

### 1. Ask a Question
```bash
cbioportal-mcp-qa ask "How many studies are there?" --agent-type cbio-agent-null
```

### 2. Batch Processing
Generate answers without running the full benchmark evaluation.
```bash
cbioportal-mcp-qa batch input/autosync-public.csv --questions 1-10 --output-dir my_results/
```

### 3. Manual Evaluation
Run the evaluation script on existing output files.
```bash
python simple_eval.py \
  --input-csv input/autosync-public.csv \
  --answers-dir my_results/ \
  --answer-column "Navbot Expected Link"
```

## Project Structure

*   `src/cbioportal_mcp_qa/`: Source code.
    *   `main.py`: CLI entry point.
    *   `benchmark.py`: Benchmarking workflow logic.
    *   `evaluation.py`: Core evaluation logic (LLM judge).
    *   `base_client.py`: Abstract base class for agents.
    *   `null_agent_client.py`: Client for `cbio-agent-null`.
    *   `llm_client.py`: Client for `mcp-clickhouse`.
*   `input/`: Benchmark datasets (e.g., `autosync-public.csv`).
*   `results/`: Generated answers and evaluation reports.
*   `simple_eval.py`: Wrapper script for running evaluation manually.
*   `agents/`: Contains Docker Compose configurations for running external agent services, such as `docker-compose.yml` for `cbio-null-agent`.