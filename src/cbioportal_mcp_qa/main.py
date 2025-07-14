"""Main CLI entry point for cBioPortal MCP QA processing."""

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
def cli(
    csv_file: Path,
    questions: str,
    output_dir: Path,
    api_key: Optional[str],
):
    """Process cBioPortal QA questions using MCP integration.
    
    CSV_FILE: Path to the CSV file containing questions
    """
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
        llm_client = LLMClient(api_key)
        output_manager = OutputManager(output_dir)
        
        # Process questions
        with tqdm(question_data, desc="Processing questions") as pbar:
            for question_num, question_type, question_text in pbar:
                pbar.set_description(f"Processing question {question_num}")
                
                # Get answer from LLM
                answer = llm_client.ask_question(question_text)
                
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