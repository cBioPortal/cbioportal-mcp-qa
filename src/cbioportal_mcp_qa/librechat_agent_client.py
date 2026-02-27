import os
import time
import httpx
from typing import Any, List
from .base_client import BaseQAClient


class LibreChatAgentClient(BaseQAClient):
    """Client for the LibreChat Remote Agents API."""

    def __init__(self, agent_id_env_var: str = "LIBRECHAT_AGENT_ID", **kwargs):
        """Initialize the client.

        Args:
            agent_id_env_var: Env var name holding the agent ID.

        Reads from environment variables:
            LIBRECHAT_BASE_URL: Base URL of the LibreChat instance.
            LIBRECHAT_API_KEY: Bearer token for authentication.
            <agent_id_env_var>: Agent ID to use (e.g. agent_4QP14nOYaCTkqK8E3Nopg).
        """
        self.base_url = os.getenv("LIBRECHAT_BASE_URL")
        if not self.base_url:
            raise ValueError("LIBRECHAT_BASE_URL environment variable must be set")
        self.base_url = self.base_url.rstrip("/")

        self.api_key = os.getenv("LIBRECHAT_API_KEY")
        if not self.api_key:
            raise ValueError("LIBRECHAT_API_KEY environment variable must be set")

        self.agent_id = os.getenv(agent_id_env_var)
        if not self.agent_id:
            raise ValueError(f"{agent_id_env_var} environment variable must be set")

    async def ask_question(self, question: str) -> str:
        """Ask a question to a LibreChat agent via the Remote Agents API.

        Args:
            question: The question to ask.

        Returns:
            Tuple of (content, model_info).
        """
        url = f"{self.base_url}/api/agents/v1/chat/completions"
        payload = {
            "model": self.agent_id,
            "messages": [{"role": "user", "content": question}],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            start_time = time.perf_counter()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=headers, timeout=300.0
                )
                response.raise_for_status()
                elapsed_seconds = time.perf_counter() - start_time

                data = response.json()

                # OpenAI-compatible response format
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    if "content" in message:
                        content = message["content"]
                else:
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
