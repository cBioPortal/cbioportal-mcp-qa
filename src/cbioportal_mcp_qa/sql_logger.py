"""SQL query logger for capturing ClickHouse MCP server communications."""

import json
import logging
import re
import asyncio
import subprocess
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pydantic_ai.mcp import MCPServerStdio


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
            
        self.queries.append(SqlQuery(
            query=query,
            timestamp=timestamp or datetime.now(),
            execution_time=execution_time,
            error=error,
            result_count=result_count
        ))
    
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


class MCPServerStdioWithLogging(MCPServerStdio):
    """MCPServerStdio wrapper that captures SQL queries from server output."""
    
    def __init__(self, sql_logger: SqlQueryLogger, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_logger = sql_logger
        self._monitoring_task = None
    
    async def start(self):
        """Start the MCP server and capture its output."""
        # Start the original process
        await super().start()
        
        # If SQL logging is enabled, start monitoring the process output
        if self.sql_logger.enabled and hasattr(self, '_process') and self._process:
            # Start background task to monitor stderr for SQL queries
            self._monitoring_task = asyncio.create_task(self._monitor_server_output())
    
    async def stop(self):
        """Stop the MCP server and monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        await super().stop()
    
    async def _monitor_server_output(self):
        """Monitor the MCP server's stderr output for SQL queries."""
        if not hasattr(self, '_process') or not self._process:
            return
            
        try:
            # Read from stderr where the MCP server logs SQL queries
            while self._process and self._process.returncode is None:
                try:
                    line = await asyncio.wait_for(self._process.stderr.readline(), timeout=0.1)
                    if not line:
                        break
                        
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str:
                        self._parse_sql_from_log_line(line_str)
                        
                except asyncio.TimeoutError:
                    # Continue monitoring even if no output for a while
                    continue
                    
        except Exception as e:
            # Don't let logging errors break the MCP server
            pass
    
    def _parse_sql_from_log_line(self, line: str):
        """Parse SQL queries from MCP server log lines."""
        # Look for the SQL query pattern in the log line
        # Example: "2025-07-16 18:57:48,741 - mcp-clickhouse - INFO - Executing SELECT query: SELECT ..."
        sql_pattern = r'(?:Executing (?:SELECT|INSERT|UPDATE|DELETE|DESCRIBE|SHOW) query:|Query:)\s*(.+)'
        match = re.search(sql_pattern, line, re.IGNORECASE)
        
        if match:
            sql_query = match.group(1).strip()
            # Clean up the SQL query
            sql_query = self._clean_sql_query(sql_query)
            if sql_query:
                # Try to extract result count if available
                result_count = self._extract_result_count(line)
                self.sql_logger.add_query(sql_query, result_count=result_count)
        
        # Also look for result count in separate lines
        result_pattern = r'Query returned (\d+) rows?'
        result_match = re.search(result_pattern, line, re.IGNORECASE)
        if result_match and self.sql_logger.queries:
            # Update the last query with result count
            self.sql_logger.queries[-1].result_count = int(result_match.group(1))
    
    def _clean_sql_query(self, query: str) -> str:
        """Clean and format the extracted SQL query."""
        # Remove any trailing log information
        query = re.sub(r'\s*\d{4}-\d{2}-\d{2}.*$', '', query)
        
        # Clean up whitespace
        query = re.sub(r'\s+', ' ', query).strip()
        
        # Only return if it looks like a meaningful SQL query
        if len(query) > 20 and any(keyword in query.upper() for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DESCRIBE', 'SHOW']):
            return query
        
        return ""
    
    def _extract_result_count(self, line: str) -> Optional[int]:
        """Extract result count from log line if available."""
        result_pattern = r'Query returned (\d+) rows?'
        match = re.search(result_pattern, line, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None


class MCPLogHandler(logging.Handler):
    """Custom log handler to capture MCP server communications."""
    
    def __init__(self, sql_logger: SqlQueryLogger):
        super().__init__()
        self.sql_logger = sql_logger
        self.setLevel(logging.DEBUG)
        
    def emit(self, record: logging.LogRecord):
        """Process log record and extract SQL queries."""
        if not self.sql_logger.enabled:
            return
            
        try:
            # Look for SQL queries in the log message
            message = record.getMessage()
            
            # Look for SQL patterns in plain text
            sql_patterns = [
                r'(?i)(?:SELECT|INSERT|UPDATE|DELETE|DESCRIBE|SHOW)\s+.*?(?:;|$)',
                r'(?i)DESCRIBE\s+\w+(?:\.\w+)*',
                r'(?i)SHOW\s+(?:TABLES|DATABASES|COLUMNS).*?(?:;|$)',
            ]
            
            for pattern in sql_patterns:
                matches = re.finditer(pattern, message, re.MULTILINE | re.DOTALL)
                for match in matches:
                    query = match.group(0).strip()
                    if len(query) > 10:  # Filter out very short matches
                        self.sql_logger.add_query(query)
                        
        except Exception as e:
            # Don't let logging errors break the application
            pass


# Global instance for the application
sql_query_logger = SqlQueryLogger()