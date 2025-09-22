"""PydanticAI client with MCP ClickHouse integration."""

import os
import asyncio
import time
import json
from typing import Optional, List, Dict, Any

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.settings import ModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .prompts import DEFAULT_SYSTEM_PROMPT
from .sql_logger import sql_query_logger, MCPServerStdioWithSQLCapture


class LLMClient:
    """PydanticAI client with MCP ClickHouse integration."""
    
    def get_sql_queries(self) -> List[Any]:
        """Get captured SQL queries for the current question.
        
        Returns:
            List of SqlQuery objects
        """
        return sql_query_logger.get_queries()
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        model: str = "anthropic:claude-sonnet-4-20250514",
        use_ollama: bool = False,
        ollama_base_url: str = "http://localhost:11434",
        clickhouse_host: Optional[str] = None,
        clickhouse_port: Optional[str] = None,
        clickhouse_user: Optional[str] = None,
        clickhouse_password: Optional[str] = None,
        clickhouse_secure: Optional[str] = None,
        clickhouse_verify: Optional[str] = None,
        clickhouse_connect_timeout: Optional[str] = None,
        clickhouse_send_receive_timeout: Optional[str] = None,
        include_sql: bool = False,
    ):
        """Initialize the client.
        
        Args:
            api_key: Anthropic API key. If None, will read from ANTHROPIC_API_KEY env var.
            model: Model to use (Anthropic or Ollama format).
            use_ollama: Whether to use Ollama instead of Anthropic.
            ollama_base_url: Base URL for Ollama server.
            clickhouse_*: ClickHouse configuration parameters.
            include_sql: Whether to capture and log SQL queries.
        """
        # Only require API key for Anthropic models
        if not use_ollama:
            api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable must be set")
        
        # Set up ClickHouse environment variables
        clickhouse_env = {}
        
        # Add required parameters
        clickhouse_env["CLICKHOUSE_HOST"] = clickhouse_host or os.getenv("CLICKHOUSE_HOST")
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
        required_params = ["CLICKHOUSE_HOST", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD"]
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
        model_settings = ModelSettings(max_tokens=4096)
        
        # Create model based on whether using Ollama or Anthropic
        if use_ollama:
            # For Ollama, create OpenAI-compatible model
            agent_model = OpenAIChatModel(
                model_name=model,  # This should be the ollama_model passed from main.py
                provider=OpenAIProvider(base_url=f"{ollama_base_url}/v1")
            )
        else:
            # For Anthropic, use model string directly
            agent_model = model
        
        self.agent = Agent(
            agent_model,
            toolsets=[self.mcp_server],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            model_settings=model_settings
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
