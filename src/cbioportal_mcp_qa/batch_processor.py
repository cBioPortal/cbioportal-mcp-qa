import os
import asyncio
from pathlib import Path
from typing import Optional

import click
from tqdm import tqdm

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from .csv_parser import load_questions, parse_question_selection
from .llm_client import get_qa_client
from .base_client import BaseQAClient
from .output_manager import OutputManager


def setup_open_telemetry_tracing():
    # Set up the tracer provider
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)

    # Add the OpenInference span processor
    endpoint = f"{os.environ['PHOENIX_COLLECTOR_ENDPOINT']}/v1/traces"

    headers = {"Authorization": f"Bearer {os.environ['PHOENIX_API_KEY']}"}
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)

    tracer_provider.add_span_processor(OpenInferenceSpanProcessor())
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))


async def async_batch_main(
    csv_file: Path,
    questions: str,
    output_dir: Path,
    agent_type: str,
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
    """Async main function for batch processing questions."""
    try:
        if enable_open_telemetry_tracing:
            setup_open_telemetry_tracing()

        # Parse question selection
        selected_questions = parse_question_selection(questions, csv_file)
        click.echo(f"Processing {len(selected_questions)} questions...")
        
        # Load questions from CSV
        question_data = load_questions(csv_file, selected_questions)
        
        if not question_data:
            click.echo("No questions found matching the selection criteria.")
            return
        
        # Initialize clients
        qa_client: BaseQAClient = get_qa_client(
            agent_type=agent_type,
            api_key=api_key,
            model=model,
            use_ollama=use_ollama,
            ollama_base_url=ollama_base_url,
            use_bedrock=use_bedrock,
            aws_profile=aws_profile,
            include_sql=include_sql,
            enable_open_telemetry_tracing=enable_open_telemetry_tracing,
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
        
        # Process questions
        with tqdm(question_data, desc="Processing questions") as pbar:
            for question_num, question_type, question_text in pbar:
                pbar.set_description(f"Processing question {question_num}")
                
                # Get answer from LLM (support both tuple and string returns)
                result = await qa_client.ask_question(question_text)
                if isinstance(result, tuple):
                    answer, model_info = result
                    model_info['agent_type'] = agent_type
                else:
                    answer, model_info = result, dict()
                
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
