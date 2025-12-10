#!/usr/bin/env python3

import click
import sys
import os

# Add src to python path to allow imports from cbioportal_mcp_qa
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from cbioportal_mcp_qa.evaluation import run_evaluation_logic

@click.command()
@click.option('--input-csv', required=True, help='Path to input CSV file containing questions and expected answers.')
@click.option('--answers-dir', required=True, help='Directory containing LLM output files.')
@click.option('--output-dir', default='evaluation_results', help='Path to save evaluation results.')
@click.option('--answer-column', default='Claude Clickhouse MCP Answer', help='Name of the column in input-csv that contains the expected human answer.')
def main(input_csv: str, answers_dir: str, output_dir: str, answer_column: str):
    '''
    Main function to evaluate LLM outputs against expected answers.
    '''
    run_evaluation_logic(input_csv, answers_dir, output_dir, answer_column)

if __name__ == '__main__':
    main()