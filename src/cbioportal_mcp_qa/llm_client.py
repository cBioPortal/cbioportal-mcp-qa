"""Client factory for cBioPortal QA agents."""

from typing import Optional

from .base_client import BaseQAClient
from .null_agent_client import CBioAgentNullClient
from .mcp_agent_client import CBioPortalMCPAgentClient


# Removed MCPClickHouseClient - no longer used after migration to Docker agent service


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
        return CBioPortalMCPAgentClient(env_var_name="MCP_CLICKHOUSE_AGENT_URL", **kwargs)
    elif agent_type == "cbio-nav-null":
        return CBioAgentNullClient(env_var_name="NULL_NAV_URL", **kwargs)
    elif agent_type == "cbio-qa-null":
        return CBioAgentNullClient(env_var_name="NULL_QA_URL", **kwargs)
    elif agent_type == "mcp-navigator-agent":
        return CBioPortalMCPAgentClient(env_var_name="CBIOPORTAL_MCP_AGENT_URL", **kwargs)
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")

