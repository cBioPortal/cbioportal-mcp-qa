import asyncio
import datetime
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .batch_processor import async_batch_main, setup_open_telemetry_tracing
from .evaluation import run_evaluation_logic

# Hardcoded mapping of agent-type to the expected answer column in the input CSV
# Since the input CSV usually has one 'Expected Answer' column, we assume that's the ground truth.
# However, if simple_eval needs to know which column to compare against (if there are multiple model outputs in the CSV),
# we might need this. But benchmark generates its OWN answers in a fresh directory.
# So we mainly need the Ground Truth column.
AGENT_COLUMN_MAPPING = {
    "mcp-clickhouse": "Navbot Expected Link",
    "cbio-agent-null": "Navbot Expected Link",
    # Add other agents here
}

async def run_benchmark(
    agent_type: str,
    questions: str,
    api_key: Optional[str],
    clickhouse_host: Optional[str],
    clickhouse_database: Optional[str],
    clickhouse_port: Optional[str],
    clickhouse_user: Optional[str],
    clickhouse_password: Optional[str],
    clickhouse_secure: Optional[str],
    clickhouse_verify: Optional[str],
    clickhouse_connect_timeout: Optional[str],
    clickhouse_send_receive_timeout: Optional[str],
    model: str,
    use_ollama: bool,
    ollama_base_url: str,
    include_sql: bool,
    enable_open_telemetry_tracing: bool,
    delay: int,
    batch_size: int,
):
    """
    Runs the benchmark for a specific agent type.
    """
    
    # 1. Setup Paths
    if enable_open_telemetry_tracing:
        setup_open_telemetry_tracing()

    # Hardcoded input CSV
    csv_file = Path("input/autosync-public.csv")

    today_str = datetime.datetime.now().strftime("%Y%m%d")
    base_results_dir = Path(f"results/{agent_type}/{today_str}")
    answers_dir = base_results_dir / "answers"
    eval_dir = base_results_dir / "eval"

    # Ensure directories exist
    answers_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    print(f"--- Starting Benchmark for {agent_type} ---")
    print(f"Output Directory: {base_results_dir}")
    # 2. Run Batch Generation
    print("Step 1: Generating Answers...")
    await async_batch_main(
        csv_file=csv_file,
        questions=questions,
        output_dir=answers_dir,
        agent_type=agent_type,
        api_key=api_key,
        clickhouse_host=clickhouse_host,
        clickhouse_database=clickhouse_database,
        clickhouse_port=clickhouse_port,
        clickhouse_user=clickhouse_user,
        clickhouse_password=clickhouse_password,
        clickhouse_secure=clickhouse_secure,
        clickhouse_verify=clickhouse_verify,
        clickhouse_connect_timeout=clickhouse_connect_timeout,
        clickhouse_send_receive_timeout=clickhouse_send_receive_timeout,
        model=model,
        use_ollama=use_ollama,
        ollama_base_url=ollama_base_url,
        include_sql=include_sql,
        enable_open_telemetry_tracing=enable_open_telemetry_tracing,
        delay=delay,
        batch_size=batch_size,
    )

    # 3. Run Evaluation
    print("Step 2: Evaluating Answers...")
    
    expected_answer_col = AGENT_COLUMN_MAPPING.get(agent_type, "Expected Answer")
    
    # Calling the refactored function
    metrics = run_evaluation_logic(
        input_csv=str(csv_file),
        answers_dir=str(answers_dir),
        output_dir=str(eval_dir),
        answer_column=expected_answer_col 
    )

    # 4. Update Leaderboard
    print("Step 3: Updating Leaderboard...")
    update_leaderboard(
        agent_type=agent_type,
        metrics=metrics,
        date_str=today_str
    )

    print(f"Benchmark Complete. Results in {base_results_dir}")


def update_leaderboard(agent_type: str, metrics: Dict[str, float], date_str: str):
    leaderboard_path = Path("LEADERBOARD.md")
    
    # Header for the table
    header = "| Date | Agent Type | Correctness | Completeness | Faithfulness | Conciseness |\n"
    separator = "|---|---|---|---|---|---|\n"
    
    row = f"| {date_str} | {agent_type} | {metrics.get('correctness_score', 0):.2f} | {metrics.get('completeness_score', 0):.2f} | {metrics.get('faithfulness_score', 0):.2f} | {metrics.get('conciseness_score', 0):.2f} |\n"
    
    content = []
    if leaderboard_path.exists():
        content = leaderboard_path.read_text().splitlines(keepends=True)
    
    # Check if we need to initialize the file
    if not content or "| Date |" not in content[0]:
        content = ["# Benchmark Leaderboard\n\n", header, separator]
    
    # Append the new row
    content.append(row)
    
    leaderboard_path.write_text("".join(content))
    print(f"Updated {leaderboard_path}")
