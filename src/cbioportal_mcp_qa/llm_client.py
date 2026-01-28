"""PydanticAI client with MCP ClickHouse integration."""

import os
import asyncio
import time
import json
from typing import Optional, List, Dict, Any, Type

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.settings import ModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .base_client import BaseQAClient
from .null_agent_client import CBioAgentNullClient
from .mcp_agent_client import CBioPortalMCPAgentClient
from .prompts import DEFAULT_SYSTEM_PROMPT
from .sql_logger import sql_query_logger, MCPServerStdioWithSQLCapture


class MCPClickHouseClient(BaseQAClient):
    """PydanticAI client with MCP ClickHouse integration."""
    
    def get_sql_queries(self) -> List[Any]:
        """Get captured SQL queries for the current question.
        
        Returns:
            List of SqlQuery objects
        """
        return sql_query_logger.get_queries()

    def get_sql_queries_markdown(self) -> str:
        """Get captured SQL queries in markdown format for the current question.

        Returns:
            Markdown string of captured queries (if supported/enabled)
        """
        if sql_query_logger.enabled:
            return sql_query_logger.get_queries_markdown()
        return ""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "anthropic:claude-sonnet-4-5-20250929",
        use_ollama: bool = False,
        ollama_base_url: str = "http://localhost:11434",
        use_bedrock: bool = False,
        aws_profile: Optional[str] = None,
        clickhouse_host: Optional[str] = None,
        clickhouse_database: Optional[str] = None,
        clickhouse_port: Optional[str] = None,
        clickhouse_user: Optional[str] = None,
        clickhouse_password: Optional[str] = None,
        clickhouse_secure: Optional[str] = None,
        clickhouse_verify: Optional[str] = None,
        clickhouse_connect_timeout: Optional[str] = None,
        clickhouse_send_receive_timeout: Optional[str] = None,
        include_sql: bool = False,
        enable_open_telemetry_tracing: bool = False,
        **kwargs,
    ):
        """Initialize the client.

        Args:
            api_key: Anthropic API key. If None, will read from ANTHROPIC_API_KEY env var.
            model: Model to use (Anthropic or Ollama format).
            use_ollama: Whether to use Ollama instead of Anthropic.
            ollama_base_url: Base URL for Ollama server.
            use_bedrock: Whether to use AWS Bedrock instead of Anthropic.
            aws_profile: AWS profile name for Bedrock authentication.
            clickhouse_*: ClickHouse configuration parameters.
            include_sql: Whether to capture and log SQL queries.
            enable_open_telemetry_tracing: Whether to capture traces with Arize Phoenix
            **kwargs: Additional arguments ignored by this client.
        """
        self.use_bedrock = use_bedrock
        self.aws_profile = aws_profile

        # Only require API key for Anthropic models (not Ollama or Bedrock)
        if not use_ollama and not use_bedrock:
            api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        
        # Set up ClickHouse environment variables
        clickhouse_env = {}
        
        # Add required parameters
        clickhouse_env["CLICKHOUSE_HOST"] = clickhouse_host or os.getenv("CLICKHOUSE_HOST")
        clickhouse_env["CLICKHOUSE_DATABASE"] = clickhouse_database or os.getenv("CLICKHOUSE_DATABASE")
        clickhouse_env["CLICKHOUSE_USER"] = clickhouse_user or os.getenv("CLICKHOUSE_USER")
        clickhouse_env["CLICKHOUSE_PASSWORD"] = clickhouse_password or os.getenv("CLICKHOUSE_PASSWORD")
        
        # Add optional parameters only if they have values
        optional_params = {
            "CLICKHOUSE_PORT": clickhouse_port or os.getenv("CLICKHOUSE_PORT"),
            "CLICKHOUSE_SECURE": clickhouse_secure or os.getenv("CLICKHOUSE_SECURE"),
            "CLICKHOUSE_VERIFY": clickhouse_verify or os.getenv("CLICKHOUSE_VERIFY"),
            "CLICKHOUSE_CONNECT_TIMEOUT": clickhouse_connect_timeout or os.getenv("CLICKHOUSE_CONNECT_TIMEOUT"),
            "CLICKHOUSE_SEND_RECEIVE_TIMEOUT": clickhouse_send_receive_timeout or os.getenv("CLICKHOUSE_SEND_RECEIVE_TIMEOUT"),
        }
        
        for key, value in optional_params.items():
            if value is not None:
                clickhouse_env[key] = value
        
        # Check for required ClickHouse parameters
        required_params = ["CLICKHOUSE_HOST", "CLICKHOUSE_DATABASE", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"]
        missing_params = [param for param in required_params if not clickhouse_env.get(param)]
        
        if missing_params:
            raise ValueError(f"Missing required ClickHouse parameters: {', '.join(missing_params)}")
        
        # Configure SQL logging
        if include_sql:
            sql_query_logger.enable()
        else:
            sql_query_logger.disable()
        
        # Configure MCP server with ClickHouse
        if include_sql:
            self.mcp_server = MCPServerStdioWithSQLCapture(
                sql_query_logger,
                command="cbioportal-mcp",
                args=[],
                env=clickhouse_env
            )
        else:
            self.mcp_server = MCPServerStdio(
                command="cbioportal-mcp",
                args=[],
                env=clickhouse_env
            )
        
        # Create agent with MCP server
        model_settings = ModelSettings(max_tokens=4096, temperature=0.0)
        
        # Create model based on provider
        if use_ollama:
            # For Ollama, create OpenAI-compatible model
            agent_model = OpenAIChatModel(
                model_name=model,  # This should be the ollama_model passed from main.py
                provider=OpenAIProvider(base_url=f"{ollama_base_url}/v1")
            )
        elif use_bedrock:
            # For Bedrock, use bedrock: prefix with model ID
            # Set up AWS credentials if profile specified
            if aws_profile:
                import boto3
                session = boto3.Session(profile_name=aws_profile)
                credentials = session.get_credentials()
                os.environ["AWS_ACCESS_KEY_ID"] = credentials.access_key
                os.environ["AWS_SECRET_ACCESS_KEY"] = credentials.secret_key
                if credentials.token:
                    os.environ["AWS_SESSION_TOKEN"] = credentials.token
                os.environ["AWS_DEFAULT_REGION"] = session.region_name or "us-east-1"

            # Use bedrock model format
            bedrock_model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
            agent_model = f"bedrock:{bedrock_model_id}"
        else:
            # For Anthropic, use model string directly
            agent_model = model
        
        self.agent = Agent(
            agent_model,
            toolsets=[self.mcp_server],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            model_settings=model_settings,
            instrument=enable_open_telemetry_tracing
        )
        
    async def ask_question(self, question: str) -> str:
        """Ask a question using PydanticAI with MCP integration.
        
        Args:
            question: The question to ask
            
        Returns:
            The response from the agent
        """
        try:
            # Clear previous queries for this question
            sql_query_logger.clear()
            
            # Use the agent's run_mcp_servers context manager
            async with self.agent:
                response = await self.agent.run(question)
                return response.output
        
        except Exception as e:
            return f"Error processing question: {str(e)}"


# Backwards compatibility
LLMClient = MCPClickHouseClient


def get_qa_client(agent_type: str = "mcp-clickhouse", **kwargs) -> BaseQAClient:
    """Factory function to get the appropriate QA client.
    
    Args:
        agent_type: Type of agent to create.
        **kwargs: Arguments to pass to the client constructor.
        
    Returns:
        An instance of BaseQAClient.
        
    Raises:
        ValueError: If agent_type is unknown.
    """
    if agent_type == "mcp-clickhouse":
        return MCPClickHouseClient(**kwargs)
    elif agent_type == "cbio-nav-null":
        return CBioAgentNullClient(env_var_name="NULL_NAV_URL", **kwargs)
    elif agent_type == "cbio-qa-null":
        return CBioAgentNullClient(env_var_name="NULL_QA_URL", **kwargs)
    elif agent_type == "cbio-mcp-agent":
        return CBioPortalMCPAgentClient(env_var_name="CBIOPORTAL_MCP_AGENT_URL", **kwargs)
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")

