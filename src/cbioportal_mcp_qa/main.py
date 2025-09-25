"""Main CLI entry point for cBioPortal MCP QA processing."""

import asyncio
from pathlib import Path
from typing import Optional

import click
from tqdm import tqdm

from .csv_parser import load_questions, parse_question_selection
from .llm_client import LLMClient
from .output_manager import OutputManager


# Shared options for both commands
def shared_options(f):
    """Decorator for common options used by both batch and ask commands."""
    options = [
        click.option(
            "--api-key",
            "-k",
            envvar="ANTHROPIC_API_KEY",
            help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
        ),
        click.option(
            "--clickhouse-host",
            envvar="CLICKHOUSE_HOST",
            help="ClickHouse host (or set CLICKHOUSE_HOST env var)",
        ),
        click.option(
            "--clickhouse-database",
            envvar="CLICKHOUSE_DATABASE",
            help="ClickHouse database (or set CLICKHOUSE_DATABASE env var)",
        ),
        click.option(
            "--clickhouse-port",
            envvar="CLICKHOUSE_PORT",
            help="ClickHouse port (or set CLICKHOUSE_PORT env var)",
        ),
        click.option(
            "--clickhouse-user",
            envvar="CLICKHOUSE_USER",
            help="ClickHouse user (or set CLICKHOUSE_USER env var)",
        ),
        click.option(
            "--clickhouse-password",
            envvar="CLICKHOUSE_PASSWORD",
            help="ClickHouse password (or set CLICKHOUSE_PASSWORD env var)",
        ),
        click.option(
            "--clickhouse-secure",
            envvar="CLICKHOUSE_SECURE",
            help="ClickHouse secure connection (or set CLICKHOUSE_SECURE env var)",
        ),
        click.option(
            "--clickhouse-verify",
            envvar="CLICKHOUSE_VERIFY",
            help="ClickHouse verify SSL (or set CLICKHOUSE_VERIFY env var)",
        ),
        click.option(
            "--clickhouse-connect-timeout",
            envvar="CLICKHOUSE_CONNECT_TIMEOUT",
            help="ClickHouse connect timeout (or set CLICKHOUSE_CONNECT_TIMEOUT env var)",
        ),
        click.option(
            "--clickhouse-send-receive-timeout",
            envvar="CLICKHOUSE_SEND_RECEIVE_TIMEOUT",
            help="ClickHouse send/receive timeout (or set CLICKHOUSE_SEND_RECEIVE_TIMEOUT env var)",
        ),
        click.option(
            "--model",
            "-m",
            default="anthropic:claude-sonnet-4-20250514",
            help="Model to use (default: claude-sonnet-4-20250514 for Anthropic, e.g., qwen3:8b for Ollama)",
        ),
        click.option(
            "--use-ollama",
            is_flag=True,
            help="Use Ollama instead of Anthropic API",
        ),
        click.option(
            "--ollama-base-url",
            default="http://localhost:11434",
            help="Ollama base URL (default: http://localhost:11434)",
        ),
        click.option(
            "--include-sql",
            is_flag=True,
            help="Include SQL queries in the output",
        ),
    ]
    
    for option in reversed(options):
        f = option(f)
    return f


@click.group()
def cli():
    """cBioPortal MCP QA tool - Ask questions about cBioPortal data using AI."""
    pass


@cli.command()
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
    "--delay",
    "-d",
    default=30,
    type=int,
    help="Delay between questions in seconds (default: 30)",
)
@click.option(
    "--batch-size",
    "-b",
    default=5,
    type=int,
    help="Number of questions to process before longer pause (default: 5)",
)
@shared_options
def batch(
    csv_file: Path,
    questions: str,
    output_dir: Path,
    delay: int,
    batch_size: int,
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
):
    """Process multiple cBioPortal QA questions from a CSV file.

    CSV_FILE: Path to the CSV file containing questions
    """
    asyncio.run(async_batch_main(
        csv_file,
        questions,
        output_dir,
        api_key,
        clickhouse_host,
        clickhouse_database,
        clickhouse_port,
        clickhouse_user,
        clickhouse_password,
        clickhouse_secure,
        clickhouse_verify,
        clickhouse_connect_timeout,
        clickhouse_send_receive_timeout,
        model,
        use_ollama,
        ollama_base_url,
        include_sql,
        delay,
        batch_size,
    ))


@cli.command()
@click.argument("question", type=str)
@click.option(
    "--output-file",
    "-o",
    type=click.Path(path_type=Path),
    help="Save output to file (optional, defaults to stdout)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["plain", "markdown"]),
    default="plain",
    help="Output format (default: plain)",
)
@shared_options
def ask(
    question: str,
    output_file: Optional[Path],
    format: str,
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
):
    """Ask a single question about cBioPortal data.
    
    QUESTION: The question to ask about the cBioPortal data
    """
    asyncio.run(async_ask_main(
        question,
        output_file,
        format,
        api_key,
        clickhouse_host,
        clickhouse_database,
        clickhouse_port,
        clickhouse_user,
        clickhouse_password,
        clickhouse_secure,
        clickhouse_verify,
        clickhouse_connect_timeout,
        clickhouse_send_receive_timeout,
        model,
        use_ollama,
        ollama_base_url,
        include_sql,
    ))


async def async_batch_main(
    csv_file: Path,
    questions: str,
    output_dir: Path,
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
    delay: int,
    batch_size: int,
):
    """Async main function for batch processing questions."""
    try:
        # Parse question selection
        selected_questions = parse_question_selection(questions, csv_file)
        click.echo(f"Processing {len(selected_questions)} questions...")
        
        # Load questions from CSV
        question_data = load_questions(csv_file, selected_questions)
        
        if not question_data:
            click.echo("No questions found matching the selection criteria.")
            return
        
        # Initialize clients
        llm_client = LLMClient(
            api_key=api_key,
            model=model,
            use_ollama=use_ollama,
            ollama_base_url=ollama_base_url,
            include_sql=include_sql,
            clickhouse_host=clickhouse_host,
            clickhouse_database=clickhouse_database,
            clickhouse_port=clickhouse_port,
            clickhouse_user=clickhouse_user,
            clickhouse_password=clickhouse_password,
            clickhouse_secure=clickhouse_secure,
            clickhouse_verify=clickhouse_verify,
            clickhouse_connect_timeout=clickhouse_connect_timeout,
            clickhouse_send_receive_timeout=clickhouse_send_receive_timeout,
        )
        output_manager = OutputManager(output_dir)
        
        # Prepare model information for output
        model_info = {
            'model': model,
            'use_ollama': use_ollama,
            'ollama_base_url': ollama_base_url,
            'max_tokens': 4096
        }
        
        # Process questions
        with tqdm(question_data, desc="Processing questions") as pbar:
            for question_num, question_type, question_text in pbar:
                pbar.set_description(f"Processing question {question_num}")
                
                # Get answer from LLM
                answer = await llm_client.ask_question(question_text)
                
                # Write result
                output_path = output_manager.write_question_result(
                    question_num, question_type, question_text, answer, include_sql, model_info
                )
                
                click.echo(f"Question {question_num} -> {output_path}")
        
        click.echo(f"✅ Completed processing {len(question_data)} questions")
        click.echo(f"📁 Results saved to: {output_dir}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise click.Abort()


async def async_ask_main(
    question: str,
    output_file: Optional[Path],
    format: str,
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
):
    """Async main function for asking a single question."""
    try:
        # Initialize LLM client
        llm_client = LLMClient(
            api_key=api_key,
            model=model,
            use_ollama=use_ollama,
            ollama_base_url=ollama_base_url,
            include_sql=include_sql,
            clickhouse_host=clickhouse_host,
            clickhouse_database=clickhouse_database,
            clickhouse_port=clickhouse_port,
            clickhouse_user=clickhouse_user,
            clickhouse_password=clickhouse_password,
            clickhouse_secure=clickhouse_secure,
            clickhouse_verify=clickhouse_verify,
            clickhouse_connect_timeout=clickhouse_connect_timeout,
            clickhouse_send_receive_timeout=clickhouse_send_receive_timeout,
        )
        
        # Get answer from LLM
        with click.progressbar(length=1, label="Processing question") as bar:
            answer = await llm_client.ask_question(question)
            bar.update(1)
        
        # Format output
        if format == "markdown":
            from datetime import datetime
            from .sql_logger import sql_query_logger
            
            output_parts = [
                f"# Question",
                "",
                f"**Question:** {question}",
                "",
                f"**Answer:**",
                "",
                answer,
            ]
            
            # Add SQL queries if enabled and available
            if include_sql and sql_query_logger.enabled:
                sql_markdown = sql_query_logger.get_queries_markdown()
                if sql_markdown:
                    output_parts.extend(["", "---", "", sql_markdown])
            
            # Add model information section
            output_parts.extend(["", "---", "", "## Model Information"])
            output_parts.append(f"**Model:** {model}")
            if use_ollama:
                output_parts.append(f"**Provider:** Ollama ({ollama_base_url})")
            else:
                output_parts.append("**Provider:** Anthropic")
            output_parts.append("**Max Tokens:** 4096")
            
            output_parts.extend(["", "---", "", f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"])
            
            formatted_output = "\n".join(output_parts)
        else:
            formatted_output = answer
        
        # Output to file or stdout
        if output_file:
            output_file.write_text(formatted_output, encoding="utf-8")
            click.echo(f"✅ Answer saved to: {output_file}")
        else:
            click.echo(formatted_output)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise click.Abort()


# For backward compatibility - support old interface
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
@click.option(
    "--model",
    "-m",
    default="anthropic:claude-sonnet-4-20250514",
    help="Model to use (default: claude-sonnet-4-20250514 for Anthropic, e.g., qwen3:8b for Ollama)",
)
@click.option(
    "--use-ollama",
    is_flag=True,
    help="Use Ollama instead of Anthropic API",
)
@click.option(
    "--ollama-base-url",
    default="http://localhost:11434",
    help="Ollama base URL (default: http://localhost:11434)",
)
@click.option(
    "--include-sql",
    is_flag=True,
    help="Include SQL queries in the output markdown files",
)
@click.option(
    "--delay",
    "-d",
    default=30,
    type=int,
    help="Delay between questions in seconds (default: 30)",
)
@click.option(
    "--batch-size",
    "-b",
    default=5,
    type=int,
    help="Number of questions to process before longer pause (default: 5)",
)
def legacy_cli(
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
    model: str,
    use_ollama: bool,
    ollama_base_url: str,
    include_sql: bool,
    delay: int,
    batch_size: int,
):
    """Process cBioPortal QA questions using MCP integration.
    
    CSV_FILE: Path to the CSV file containing questions
    
    Note: This interface is deprecated. Use 'cbioportal-mcp-qa batch' instead.
    """
    click.echo("⚠️  Warning: This interface is deprecated. Use 'cbioportal-mcp-qa batch' instead.", err=True)
    
    asyncio.run(async_batch_main(
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
        model,
        use_ollama,
        ollama_base_url,
        include_sql,
        delay,
        batch_size,
    ))


if __name__ == "__main__":
    cli()