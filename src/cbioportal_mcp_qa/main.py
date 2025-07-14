"""Main CLI entry point for cBioPortal MCP QA processing."""

import asyncio
from pathlib import Path
from typing import Optional

import click
from tqdm import tqdm

from .csv_parser import load_questions, parse_question_selection
from .llm_client import LLMClient
from .output_manager import OutputManager


@click.command()
@click.argument("csv_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--questions",
    "-q",
    default="all",
    help="Questions to process. Examples: 'all', '1-5', '1,3,5'",
)
@click.option(
    "--output-dir",
    "-o",
    default="export",
    type=click.Path(path_type=Path),
    help="Output directory for markdown files",
)
@click.option(
    "--api-key",
    "-k",
    envvar="ANTHROPIC_API_KEY",
    help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
)
@click.option(
    "--clickhouse-host",
    envvar="CLICKHOUSE_HOST",
    help="ClickHouse host (or set CLICKHOUSE_HOST env var)",
)
@click.option(
    "--clickhouse-port",
    envvar="CLICKHOUSE_PORT",
    help="ClickHouse port (or set CLICKHOUSE_PORT env var)",
)
@click.option(
    "--clickhouse-user",
    envvar="CLICKHOUSE_USER",
    help="ClickHouse user (or set CLICKHOUSE_USER env var)",
)
@click.option(
    "--clickhouse-password",
    envvar="CLICKHOUSE_PASSWORD",
    help="ClickHouse password (or set CLICKHOUSE_PASSWORD env var)",
)
@click.option(
    "--clickhouse-secure",
    envvar="CLICKHOUSE_SECURE",
    help="ClickHouse secure connection (or set CLICKHOUSE_SECURE env var)",
)
@click.option(
    "--clickhouse-verify",
    envvar="CLICKHOUSE_VERIFY",
    help="ClickHouse verify SSL (or set CLICKHOUSE_VERIFY env var)",
)
@click.option(
    "--clickhouse-connect-timeout",
    envvar="CLICKHOUSE_CONNECT_TIMEOUT",
    help="ClickHouse connect timeout (or set CLICKHOUSE_CONNECT_TIMEOUT env var)",
)
@click.option(
    "--clickhouse-send-receive-timeout",
    envvar="CLICKHOUSE_SEND_RECEIVE_TIMEOUT",
    help="ClickHouse send/receive timeout (or set CLICKHOUSE_SEND_RECEIVE_TIMEOUT env var)",
)
def cli(
    csv_file: Path,
    questions: str,
    output_dir: Path,
    api_key: Optional[str],
    clickhouse_host: Optional[str],
    clickhouse_port: Optional[str],
    clickhouse_user: Optional[str],
    clickhouse_password: Optional[str],
    clickhouse_secure: Optional[str],
    clickhouse_verify: Optional[str],
    clickhouse_connect_timeout: Optional[str],
    clickhouse_send_receive_timeout: Optional[str],
):
    """Process cBioPortal QA questions using MCP integration.
    
    CSV_FILE: Path to the CSV file containing questions
    """
    asyncio.run(async_main(
        csv_file,
        questions,
        output_dir,
        api_key,
        clickhouse_host,
        clickhouse_port,
        clickhouse_user,
        clickhouse_password,
        clickhouse_secure,
        clickhouse_verify,
        clickhouse_connect_timeout,
        clickhouse_send_receive_timeout,
    ))


async def async_main(
    csv_file: Path,
    questions: str,
    output_dir: Path,
    api_key: Optional[str],
    clickhouse_host: Optional[str],
    clickhouse_port: Optional[str],
    clickhouse_user: Optional[str],
    clickhouse_password: Optional[str],
    clickhouse_secure: Optional[str],
    clickhouse_verify: Optional[str],
    clickhouse_connect_timeout: Optional[str],
    clickhouse_send_receive_timeout: Optional[str],
):
    """Async main function for processing questions."""
    try:
        # Parse question selection
        selected_questions = parse_question_selection(questions)
        click.echo(f"Processing {len(selected_questions)} questions...")
        
        # Load questions from CSV
        question_data = load_questions(csv_file, selected_questions)
        
        if not question_data:
            click.echo("No questions found matching the selection criteria.")
            return
        
        # Initialize clients
        llm_client = LLMClient(
            api_key=api_key,
            clickhouse_host=clickhouse_host,
            clickhouse_port=clickhouse_port,
            clickhouse_user=clickhouse_user,
            clickhouse_password=clickhouse_password,
            clickhouse_secure=clickhouse_secure,
            clickhouse_verify=clickhouse_verify,
            clickhouse_connect_timeout=clickhouse_connect_timeout,
            clickhouse_send_receive_timeout=clickhouse_send_receive_timeout,
        )
        output_manager = OutputManager(output_dir)
        
        # Process questions
        with tqdm(question_data, desc="Processing questions") as pbar:
            for question_num, question_type, question_text in pbar:
                pbar.set_description(f"Processing question {question_num}")
                
                # Get answer from LLM
                answer = await llm_client.ask_question(question_text)
                
                # Write result
                output_path = output_manager.write_question_result(
                    question_num, question_type, question_text, answer
                )
                
                click.echo(f"Question {question_num} -> {output_path}")
        
        click.echo(f"✅ Completed processing {len(question_data)} questions")
        click.echo(f"📁 Results saved to: {output_dir}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()