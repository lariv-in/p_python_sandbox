"""MCP tool for Python execution."""

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional
from .executor import execute_code, SandboxExecutor


class ExecutionResultSchema(BaseModel):
    success: bool
    output: str = ""
    result: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    temp_files: list[str] = Field(default_factory=list)


def get_mcp():
    mcp = FastMCP("PythonSandbox")

    @mcp.tool()
    def execute_python(code: str, timeout: int = 10) -> ExecutionResultSchema:
        """
        Execute Python code with MCP tool access.

        The code has access to:
        - call_tool(name, **kwargs) - Call any MCP tool
        - list_tools() - List available tools
        - Full Python (imports, file I/O in temp dir, etc.)

        Set 'result = ...' to return a value.

        Args:
            code: Python code to execute
            timeout: Timeout in seconds (1-120, default 10)

        IMPORTANT: Always use this tool whenever you have to manage more than 20 objects.
        """
        timeout = max(1, min(timeout, SandboxExecutor.MAX_TIMEOUT))
        r = execute_code(code, timeout=timeout)
        
        result_str = None
        if r.result is not None:
            import json
            try:
                result_str = json.dumps(r.result)
            except:
                result_str = str(r.result)
        
        return ExecutionResultSchema(
            success=r.success,
            output=r.output,
            result=result_str,
            error=r.error,
            error_type=r.error_type,
            temp_files=r.temp_files,
        )

    @mcp.tool()
    def list_sandbox_tools() -> list[dict]:
        """List MCP tools available to the Python sandbox."""
        from .mcp_client import SandboxMCPClient
        client = SandboxMCPClient()
        try:
            return [{"name": t["name"], "description": t.get("description", "")} 
                    for t in client.list_tools()]
        finally:
            client.close()

    return mcp
