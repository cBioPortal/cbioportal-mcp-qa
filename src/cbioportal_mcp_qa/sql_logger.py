"""SQL query logger for capturing ClickHouse MCP server communications."""

import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.abstract import ToolsetTool

@dataclass
class SqlQuery:
    """Represents a captured SQL query."""
    query: str
    timestamp: datetime
    execution_time: Optional[float] = None
    error: Optional[str] = None
    result_count: Optional[int] = None


class SqlQueryLogger:
    """Captures and stores SQL queries from MCP server communications."""
    
    def __init__(self):
        self.queries: List[SqlQuery] = []
        self.enabled = False
        
    def enable(self):
        """Enable SQL query logging."""
        self.enabled = True
        
    def disable(self):
        """Disable SQL query logging."""
        self.enabled = False
        
    def clear(self):
        """Clear all captured queries."""
        self.queries.clear()
    
    def add_query(self, query: str, timestamp: Optional[datetime] = None, 
                  execution_time: Optional[float] = None, error: Optional[str] = None,
                  result_count: Optional[int] = None):
        """Add a SQL query to the log."""
        if not self.enabled:
            return
            
        # Clean up the query
        query = self._clean_sql_query(query)
        if not query:
            return
        
        # Check if we already have this exact query (avoid duplicates)
        if any(existing.query == query for existing in self.queries):
            return
            
        self.queries.append(SqlQuery(
            query=query,
            timestamp=timestamp or datetime.now(),
            execution_time=execution_time,
            error=error,
            result_count=result_count
        ))
    
    def _clean_sql_query(self, query: str) -> str:
        """Clean and format the SQL query."""
        if not query:
            return ""
        
        # Remove any log timestamps or prefixes that might have snuck in
        lines = []
        for line in query.split('\n'):
            line = line.strip()
            # Skip lines that look like log entries
            if line and not line.startswith('2025-') and 'INFO' not in line and 'ERROR' not in line:
                lines.append(line)
        
        query = '\n'.join(lines)
        
        # Only return if it looks like a meaningful SQL query
        if len(query) > 20 and any(keyword in query.upper() for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DESCRIBE', 'SHOW']):
            return query
        
        return ""
    
    def get_queries(self) -> List[SqlQuery]:
        """Get all captured queries."""
        return self.queries.copy()
    
    def get_queries_markdown(self) -> str:
        """Format queries as markdown."""
        if not self.queries:
            return ""
            
        markdown_lines = ["## SQL Queries Executed", ""]
        
        for i, query in enumerate(self.queries, 1):
            markdown_lines.append(f"### Query {i}")
            markdown_lines.append(f"**Timestamp:** {query.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if query.execution_time:
                markdown_lines.append(f"**Execution Time:** {query.execution_time:.3f}s")
            
            if query.result_count is not None:
                markdown_lines.append(f"**Result Count:** {query.result_count}")
                
            if query.error:
                markdown_lines.append(f"**Error:** {query.error}")
            
            markdown_lines.append("")
            markdown_lines.append("```sql")
            markdown_lines.append(query.query)
            markdown_lines.append("```")
            markdown_lines.append("")
        
        return "\n".join(markdown_lines)


class MCPServerStdioWithSQLCapture(MCPServerStdio):
    """MCPServerStdio that captures SQL queries from tool arguments."""
    
    def __init__(self, sql_logger: SqlQueryLogger, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_logger = sql_logger
        
    async def call_tool(self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],) -> Any:
        """Override call_tool to capture SQL queries during tool execution."""
        # Capture SQL query directly from tool arguments
        if self.sql_logger.enabled and 'query' in tool_args:
            sql_query = tool_args['query']
            self.sql_logger.add_query(sql_query)
        
        # Call the original tool
        return await super().call_tool(name, tool_args, ctx, tool)
    
    


# Global instance for the application
sql_query_logger = SqlQueryLogger()