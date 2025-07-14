"""Simple Anthropic API client with MCP integration."""

import os
from typing import Optional

import anthropic


class LLMClient:
    """Simple client for Anthropic API with MCP integration."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the client.
        
        Args:
            api_key: Anthropic API key. If None, will read from ANTHROPIC_API_KEY env var.
        """
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable must be set")
        
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def ask_question(self, question: str) -> str:
        """Ask a question using the Anthropic API with MCP integration.
        
        Args:
            question: The question to ask
            
        Returns:
            The response from the API
        """
        system_prompt = """You are a helpful assistant with access to cBioPortal data through MCP integration.
        
When answering questions about cBioPortal data:
1. Use the available MCP tools to query the ClickHouse database
2. Provide accurate, data-driven responses
3. Include specific numbers and statistics when available
4. Be clear about any limitations or assumptions
5. Format your response in a clear, structured way

If you need to access cBioPortal data, use the MCP tools available to you."""
        
        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": question}
                ]
            )
            
            return response.content[0].text
        
        except Exception as e:
            return f"Error processing question: {str(e)}"