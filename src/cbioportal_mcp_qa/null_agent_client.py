import os
import httpx
from typing import Any, List, Optional
from .base_client import BaseQAClient

class CBioAgentNullClient(BaseQAClient):
    """Client for the cBio-nav-null API."""

    def __init__(self, env_var_name: str = "NULL_NAV_URL", **kwargs):
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
        """Ask a question to the null agent API.

        Args:
            question: The question to ask.

        Returns:
            The agent's response.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "messages": [{"role": "user", "content": question}],
            "stream": False
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=60.0)
                response.raise_for_status()
                
                # Assume standard OpenAI-like response format based on endpoint name
                # or just look for 'content' in the response.
                # Since the spec didn't define the response format explicitly beyond input,
                # I'll assume a standard OpenAI chat completion response structure 
                # or a simple JSON with 'content' or 'response'.
                # Let's try standard OpenAI format first: choices[0].message.content
                # If that fails, we'll dump the whole JSON.
                
                data = response.json()
                
                # check for OpenAI format
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    if "content" in message:
                        return message["content"]
                
                # Fallback: if it's just a direct dict
                return str(data)

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
