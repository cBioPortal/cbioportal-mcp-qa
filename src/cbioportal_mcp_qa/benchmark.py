import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .batch_processor import async_batch_main, setup_open_telemetry_tracing
from .evaluation import run_evaluation_logic

# Hardcoded mapping of agent-type to the expected answer column in the input CSV
# Since the input CSV usually has one 'Expected Answer' column, we assume that's the ground truth.
# However, if simple_eval needs to know which column to compare against (if there are multiple model outputs in the CSV),
# we might need this. But benchmark generates its OWN answers in a fresh directory.
# So we mainly need the Ground Truth column.
AGENT_COLUMN_MAPPING = {
    "mcp-clickhouse": "DBBot Expected Answer",
    "cbio-nav-null": "Navbot Expected Link(s)",
    "cbio-qa-null": "DBBot Expected Answer",
    "mcp-navigator-agent": "Navbot Expected Link(s)",
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
    use_bedrock: bool,
    aws_profile: Optional[str],
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
    csv_file = Path("input/benchmark-testing.csv")

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
        use_bedrock=use_bedrock,
        aws_profile=aws_profile,
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
        answer_column=expected_answer_col,
        use_bedrock=use_bedrock,
        aws_profile=aws_profile,
    )

    # 4. Update Leaderboard
    print("Step 3: Updating Leaderboard...")
    regenerate_leaderboard()

    print(f"Benchmark Complete. Results in {base_results_dir}")


def regenerate_leaderboard():
    """
    Scans the results/ directory for all evaluation results, aggregates them,
    and overwrites LEADERBOARD.md with a sorted table.
    """
    leaderboard_path = Path("LEADERBOARD.md")
    results_root = Path("results")
    
    if not results_root.exists():
        print("No results directory found.")
        return

    aggregated_data = []

    # Walk through results directory structure: results/{agent_type}/{date}/eval/*.csv
    for agent_dir in results_root.iterdir():
        if not agent_dir.is_dir():
            continue
        agent_type = agent_dir.name
        # print(f"Found agent dir: {agent_type}")
        
        for date_dir in agent_dir.iterdir():
            if not date_dir.is_dir():
                continue
            date_str = date_dir.name
            # print(f"  Found date dir: {date_str}")
            
            eval_dir = date_dir / "eval"
            if not eval_dir.exists():
                # print(f"    No eval dir in {date_dir}")
                continue
                
            # Find the latest evaluation CSV in this folder
            csv_files = list(eval_dir.glob("evaluation_*.csv"))
            if not csv_files:
                # print(f"    No CSVs in {eval_dir}")
                continue
            
            # Use the most recent CSV if multiple exist (though usually one per run)
            csv_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            latest_csv = csv_files[0]
            # print(f"    Processing {latest_csv}")
            
            try:
                df = pd.read_csv(latest_csv, comment='#')
                
                # Identify score columns
                score_cols = [c for c in df.columns if c.endswith('_score')]
                if not score_cols:
                    continue
                
                # Calculate averages
                averages = df[score_cols].astype(float).mean().to_dict()
                
                # Create row record
                record = {
                    "Date": date_str,
                    "Agent Type": agent_type,
                }
                record.update(averages)
                aggregated_data.append(record)
                
            except Exception as e:
                print(f"Error reading {latest_csv}: {e}")
                continue

    if not aggregated_data:
        print("No evaluation data found to generate leaderboard.")
        return

    # Create DataFrame
    df_leaderboard = pd.DataFrame(aggregated_data)
    
    # Sort by Date (descending), then Correctness Score (descending)
    df_leaderboard.sort_values(by=["Date", "correctness_score"], ascending=[False, False], inplace=True)
    
    # Format headers: 'correctness_score' -> 'Correctness Score'
    df_leaderboard.columns = [c.replace('_', ' ').title() if c.endswith('_score') else c for c in df_leaderboard.columns]
    
    # Identify score columns again after rename
    score_cols_display = [c for c in df_leaderboard.columns if ' Score' in c]
    # Sort score columns alphabetically
    score_cols_display.sort()
    
    # Reorder columns: Date, Agent Type, ...Scores
    final_cols = ["Date", "Agent Type"] + score_cols_display
    df_leaderboard = df_leaderboard[final_cols]
    
    # Format scores to 2 decimal places
    for col in score_cols_display:
        df_leaderboard[col] = df_leaderboard[col].map('{:.2f}'.format)

    # Convert to Markdown table
    markdown_table = df_leaderboard.to_markdown(index=False)
    
    # Add Title
    final_content = "# Benchmark Leaderboard\n\n" + markdown_table + "\n"
    
    leaderboard_path.write_text(final_content)
    print(f"Regenerated {leaderboard_path} with {len(aggregated_data)} entries.")
