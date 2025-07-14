"""PydanticAI client with MCP ClickHouse integration."""

import os
from typing import Optional

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio


class LLMClient:
    """PydanticAI client with MCP ClickHouse integration."""
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        clickhouse_host: Optional[str] = None,
        clickhouse_port: Optional[str] = None,
        clickhouse_user: Optional[str] = None,
        clickhouse_password: Optional[str] = None,
        clickhouse_secure: Optional[str] = None,
        clickhouse_verify: Optional[str] = None,
        clickhouse_connect_timeout: Optional[str] = None,
        clickhouse_send_receive_timeout: Optional[str] = None,
    ):
        """Initialize the client.
        
        Args:
            api_key: Anthropic API key. If None, will read from ANTHROPIC_API_KEY env var.
            clickhouse_*: ClickHouse configuration parameters.
        """
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
        
        # Configure MCP server with ClickHouse
        self.mcp_server = MCPServerStdio(
            command="mcp-clickhouse",
            args=[],
            env=clickhouse_env
        )
        
        # Create agent with MCP server
        self.agent = Agent(
            'anthropic:claude-3-5-sonnet-20241022',
            mcp_servers=[self.mcp_server],
            system_prompt="""You are a helpful assistant with access to cBioPortal data through MCP integration.

Use the cBioPortal clickhouse cgds_public_2025_06_24 database to answer user questions. The database has tables for patients, sample and associated clinical data. Studies are in the cancer_study table. Focus on data in the msk_chord_2024 if no specific studies are mentioned. There are genomic alterations in mutation, cna, structural_variant and related columns. The events table determines treatments for each patient.

cBioPortal Cohort URLs can be constructed like this for example where P-0001534 is a PATIENT_ID: `https://www.cbioportal.org/study/summary?id=msk_chord_2024#filterJson={%22patientIdentifiers%22:[{%22studyId%22:%22msk_chord_2024%22,%22patientId%22:%22P-0001534%22}]}`. When you talk about a specific group of patient provide links using that URL pattern (don't explain to the user how to make them, but just give the URL).

Always aim to use the clickhouse MCP server unless specifically prompted to do something else.

When answering questions about cBioPortal data:
1. Use the available MCP tools to query the ClickHouse database
2. Provide accurate, data-driven responses
3. Include specific numbers and statistics when available
4. Be clear about any limitations or assumptions
5. Format your response in a clear, structured way

If you need to access cBioPortal data, use the MCP tools available to you."""
        )
    
    async def ask_question(self, question: str) -> str:
        """Ask a question using PydanticAI with MCP integration.
        
        Args:
            question: The question to ask
            
        Returns:
            The response from the agent
        """
        try:
            # Use the agent's run_mcp_servers context manager
            async with self.agent.run_mcp_servers():
                response = await self.agent.run(question)
                return response.data
        
        except Exception as e:
            return f"Error processing question: {str(e)}"