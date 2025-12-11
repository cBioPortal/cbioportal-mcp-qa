from abc import ABC, abstractmethod
from typing import Any, List

class BaseQAClient(ABC):
    """Abstract base class for QA clients."""

    @abstractmethod
    async def ask_question(self, question: str) -> str:
        """Ask a question and return the answer.
        
        Args:
            question: The question to ask
            
        Returns:
            The response from the agent
        """
        pass

    @abstractmethod
    def get_sql_queries(self) -> List[Any]:
        """Get captured SQL queries for the current question.
        
        Returns:
            List of captured queries (if supported/enabled)
        """
        return []

    @abstractmethod
    def get_sql_queries_markdown(self) -> str:
        """Get captured SQL queries in markdown format for the current question.

        Returns:
            Markdown string of captured queries (if supported/enabled)
        """
        return ""
