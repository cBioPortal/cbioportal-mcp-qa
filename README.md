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
2.  `mcp-navigator-agent`: cBioPortal MCP agent service (HTTP API wrapper around MCP).
3.  `cbio-nav-null`: A baseline/testing agent (or a specific implementation hosted at a URL).
4.  `cbio-qa-null`: Another baseline/testing agent, similar to `cbio-nav-null` but using a different configuration.

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
*   `ANTHROPIC_API_KEY`: Required for the LLM judge (evaluation). Alternatively, use AWS Bedrock with `--use-bedrock` and `--aws-profile`.

**For `mcp-navigator-agent`:**
*   `CBIOPORTAL_MCP_AGENT_URL`: URL of the cBioPortal MCP agent API (e.g., `http://localhost:8080`).

**For `cbio-nav-null`:**
*   `NULL_NAV_URL`: URL of the agent API (e.g., `http://localhost:5000`).

**For `cbio-qa-null`:**
*   `NULL_QA_URL`: URL of the agent API (e.g., `http://localhost:5002`).

**For `mcp-clickhouse`:**
*   `MCP_CLICKHOUSE_AGENT_URL`: URL of the MCP ClickHouse agent API (e.g., `http://localhost:8080`).

**Optional (Tracing):**
*   `PHOENIX_API_KEY`: For Arize Phoenix tracing.
*   `PHOENIX_COLLECTOR_ENDPOINT`: Tracing endpoint.

## Benchmarking (Primary Workflow)

The `benchmark` command is the main way to evaluate an agent. It automates generation, evaluation, and leaderboard updates.

```bash
# Run benchmark for the cBioPortal MCP agent
cbioportal-mcp-qa benchmark --agent-type mcp-navigator-agent --questions 1-5

# Run benchmark for the null agent
cbioportal-mcp-qa benchmark --agent-type cbio-nav-null --questions 1-5

# Run benchmark for the direct MCP connection
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
# Ask using the cBioPortal MCP agent
cbioportal-mcp-qa ask "How many studies are there?" --agent-type mcp-navigator-agent

# Ask using a null agent
cbioportal-mcp-qa ask "How many studies are there?" --agent-type cbio-nav-null
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

## Adding New Agents

To integrate a new agent into the benchmarking system:

1.  **Create a new client class**: In `src/cbioportal_mcp_qa/`, create a new Python file (e.g., `my_new_agent_client.py`) with a class that inherits from `BaseQAClient` and implements the `ask_question` and `get_sql_queries_markdown` methods.

2.  **Register the client in `llm_client.py`**: Open `src/cbioportal_mcp_qa/llm_client.py`:
    *   Import your new client class.
    *   Add a new `elif` condition in the `get_qa_client` factory function to return an instance of your new client when a specific `--agent-type` string is provided.

    ```python
    # Example in src/cbioportal_mcp_qa/llm_client.py
    from .my_new_agent_client import MyNewAgentClient
    # ...
    def get_qa_client(agent_type: str = "mcp-clickhouse", **kwargs) -> BaseQAClient:
        if agent_type == "mcp-clickhouse":
            return MCPClickHouseClient(**kwargs)
        elif agent_type == "cbio-nav-null":
            return CBioAgentNullClient(**kwargs)
        elif agent_type == "my-new-agent": # Your new agent type
            return MyNewAgentClient(**kwargs)
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
    ```

3.  **Update `AGENT_COLUMN_MAPPING` in `benchmark.py`**: In `src/cbioportal_mcp_qa/benchmark.py`, add an entry to the `AGENT_COLUMN_MAPPING` dictionary. This maps your new `agent_type` to the corresponding column in your `input/autosync-public.csv` (or other benchmark CSV) that contains the *expected answer* for evaluation.

    ```python
    # Example in src/cbioportal_mcp_qa/benchmark.py
    AGENT_COLUMN_MAPPING = {
        "mcp-clickhouse": "DBBot Expected Answer",
        "cbio-nav-null": "Navbot Expected Link",
        "my-new-agent": "My New Agent Expected Answer Column", # Your agent's expected answer column
    }
    ```

4.  **Add Configuration (if any)**: If your new agent requires specific environment variables or CLI options, update the `Configuration` section in `README.md` and add `click.option` decorators in `src/cbioportal_mcp_qa/main.py` if needed.

## Project Structure

*   `src/cbioportal_mcp_qa/`: Source code.
    *   `main.py`: CLI entry point.
    *   `benchmark.py`: Benchmarking workflow logic.
    *   `evaluation.py`: Core evaluation logic (LLM judge).
    *   `base_client.py`: Abstract base class for agents.
    *   `null_agent_client.py`: Client for `cbio-nav-null`.
    *   `llm_client.py`: Client for `mcp-clickhouse`.
*   `input/`: Benchmark datasets (e.g., `autosync-public.csv`).
*   `results/`: Generated answers and evaluation reports.
*   `simple_eval.py`: Wrapper script for running evaluation manually.
*   `agents/`: Contains Docker Compose configurations for running external agent services, such as `docker-compose.yml` for `cbio-null-agent`.
