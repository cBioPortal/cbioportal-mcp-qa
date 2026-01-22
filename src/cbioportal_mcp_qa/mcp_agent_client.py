import os
import time
import httpx
from typing import Any, List, Optional
from .base_client import BaseQAClient

class CBioPortalMCPAgentClient(BaseQAClient):
    """Client for the cBioPortal MCP Agent API."""

    def __init__(self, env_var_name: str = "CBIOPORTAL_MCP_AGENT_URL", **kwargs):
        """Initialize the client.
        
        Args:
            env_var_name: The name of the environment variable holding the base URL.
            **kwargs: Additional arguments. 
        """
        self.base_url = os.getenv(env_var_name)
        if not self.base_url:
            raise ValueError(f"{env_var_name} environment variable must be set")
        
        # Remove trailing slash if present for consistent path joining
        self.base_url = self.base_url.rstrip("/")

    async def ask_question(self, question: str) -> str:
        """Ask a question to the cBioPortal MCP agent API.

        Args:
            question: The question to ask.

        Returns:
            The agent's response.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "messages": [{"role": "user", "content": question}],
            "stream": False,
            "include_model_info": True
        }

        try:
            start_time = time.perf_counter()
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=300.0)  # 5 minutes for complex queries
                response.raise_for_status()
                elapsed_seconds = time.perf_counter() - start_time
                
                data = response.json()
                                
                # check for OpenAI format
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    if "content" in message:
                        content = message["content"]
                else:
                    # Fallback: if it's just a direct dict
                    content = str(data)
                    
                model_info = data.get("model_info") or dict()
                model_info["response_time_seconds"] = elapsed_seconds
                
                return content, model_info

        except httpx.HTTPStatusError as e:
            return f"Error: API request failed with status {e.response.status_code}: {e.response.text}"
        except Exception as e:
            return f"Error connecting to agent: {str(e)}"

    def get_sql_queries(self) -> List[Any]:
        """Get captured SQL queries. Not supported for this agent."""
        return []

    def get_sql_queries_markdown(self) -> str:
        """Get captured SQL queries in markdown. Not supported for this agent."""
        return ""
