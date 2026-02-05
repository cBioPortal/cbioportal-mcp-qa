#!/usr/bin/env python3

from functools import lru_cache


from cbioportal_mcp_qa.evaluation import evaluate
from src.cbioportal_mcp_qa.llm_client import LLMClient
from src.cbioportal_mcp_qa.main import setup_open_telemetry_tracing

import pandas as pd
import click
from anthropic import Client
from dotenv import load_dotenv

import phoenix as px
from phoenix.experiments import run_experiment
from phoenix.experiments.types import Example
from phoenix.experiments.types import EvaluationResult

load_dotenv()

llm_client = Client()
px_client = px.Client()

setup_open_telemetry_tracing()
cbio_llm_client = LLMClient(enable_open_telemetry_tracing=True)

def get_value(param):
    if isinstance(param, str):
        return param
    elif isinstance(param, dict):
        if len(param) == 1:
            return next(iter(param.values()))
        else:
            raise ValueError("Dictionary must have exactly one entry")
    else:
        raise TypeError("Parameter must be a string or a dictionary with one entry")

def ask_cbio_task(example: Example) -> str:
    return cbio_llm_client.ask_question(get_value(example.input))

@lru_cache(maxsize=None)
def simple_eval(input, expected, output) -> EvaluationResult:
    return evaluate(llm_client, input, expected, output)

def correctness(input, expected, output) -> EvaluationResult:
    simple_eval_result = simple_eval(get_value(input), get_value(expected), get_value(output))
    return EvaluationResult(simple_eval_result['correctness_score'], 'correctness', simple_eval_result['correctness_explanation'])

def completeness(input, expected, output) -> EvaluationResult:
    simple_eval_result = simple_eval(get_value(input), get_value(expected), get_value(output))
    return EvaluationResult(simple_eval_result['completeness_score'], 'completeness', simple_eval_result['completeness_explanation'])

def conciseness(input, expected, output) -> EvaluationResult:
    simple_eval_result = simple_eval(get_value(input), get_value(expected), get_value(output))
    return EvaluationResult(simple_eval_result['conciseness_score'], 'conciseness', simple_eval_result['conciseness_explanation'])

def faithfulness(input, expected, output) -> EvaluationResult:
    simple_eval_result = simple_eval(get_value(input), get_value(expected), get_value(output))
    return EvaluationResult(simple_eval_result['faithfulness_score'], 'faithfulness', simple_eval_result['faithfulness_explanation'])

@click.command()
@click.option('--dataset-name', default='MCP-QA-base-set', help='The name of the Arize Phoenix dataset.')
@click.option('--dataset-version-id', default=None, help='Version id of the dataset. It would take the latest version by default.')
@click.option('--code-version-id', default=None, help='Code version of the agent to link with possible code changes. e.g. git hash code')
def main(dataset_name: str, dataset_version_id: str, code_version_id: str):
    dataset = px_client.get_dataset(name=dataset_name, version_id=dataset_version_id)
    run_experiment(dataset, 
        task=ask_cbio_task,
        evaluators=[
            correctness,
            completeness,
            conciseness,
            faithfulness,
        ],
        experiment_metadata={'code_version': code_version_id} if code_version_id is not None else None)

if __name__ == '__main__':
    main()