"""
Python executor with process isolation.

Runs Python code in a subprocess with:
- Process isolation (can be killed on timeout)
- MCP tool access via call_tool()
- Full Python capabilities (imports allowed)
"""

import tempfile
import shutil
import multiprocessing as mp
from multiprocessing.connection import Connection
from typing import Any
from dataclasses import dataclass, field
import os
import sys
from io import StringIO


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    output: str = ""
    result: Any = None
    error: str | None = None
    error_type: str | None = None
    temp_files: list[str] = field(default_factory=list)


# Message types
MSG_TOOL_CALL = "tool_call"
MSG_TOOL_RESULT = "tool_result"
MSG_LIST_TOOLS = "list_tools"
MSG_DONE = "done"
MSG_ERROR = "error"


def _worker(code: str, temp_dir: str, conn: Connection):
    """Worker process that executes Python code."""
    
    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()
    
    # Change to temp dir
    old_cwd = os.getcwd()
    os.chdir(temp_dir)
    
    try:
        # Create call_tool function that proxies to parent
        def call_tool(name: str, **kwargs) -> Any:
            conn.send({"type": MSG_TOOL_CALL, "name": name, "kwargs": kwargs})
            response = conn.recv()
            if response["type"] == MSG_ERROR:
                raise RuntimeError(response["error"])
            return response["result"]
        
        def list_tools() -> list[dict]:
            conn.send({"type": MSG_LIST_TOOLS})
            response = conn.recv()
            if response["type"] == MSG_ERROR:
                raise RuntimeError(response["error"])
            return response["result"]
        
        # Execute code with call_tool available
        exec_globals = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "call_tool": call_tool,
            "list_tools": list_tools,
        }
        exec_locals = {}
        
        exec(code, exec_globals, exec_locals)
        
        # Get result
        result = exec_locals.get("result", None)
        output = captured_output.getvalue()
        temp_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
        
        conn.send({
            "type": MSG_DONE,
            "success": True,
            "output": output,
            "result": result,
            "temp_files": temp_files,
        })
        
    except Exception as e:
        import traceback
        conn.send({
            "type": MSG_DONE,
            "success": False,
            "output": captured_output.getvalue(),
            "result": None,
            "error": f"{e}\n{traceback.format_exc()}",
            "error_type": type(e).__name__,
            "temp_files": [],
        })
    finally:
        sys.stdout = old_stdout
        os.chdir(old_cwd)


class SandboxExecutor:
    """Executes Python code in an isolated subprocess."""
    
    MAX_TIMEOUT = 120
    DEFAULT_TIMEOUT = 10

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = min(timeout, self.MAX_TIMEOUT)

    def execute(self, code: str) -> ExecutionResult:
        temp_dir = tempfile.mkdtemp(prefix="sandbox_")
        
        from .mcp_client import SandboxMCPClient
        mcp_client = SandboxMCPClient()
        
        parent_conn, child_conn = mp.Pipe()
        
        ctx = mp.get_context('spawn')
        process = ctx.Process(target=_worker, args=(code, temp_dir, child_conn))
        process.start()
        
        try:
            return self._handle_comm(process, parent_conn, mcp_client, temp_dir)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            parent_conn.close()
            child_conn.close()
            mcp_client.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _handle_comm(self, process, conn, mcp_client, temp_dir) -> ExecutionResult:
        import time
        start = time.time()
        
        while True:
            remaining = self.timeout - (time.time() - start)
            if remaining <= 0:
                return ExecutionResult(
                    success=False,
                    error=f"Timeout after {self.timeout}s",
                    error_type="TimeoutError",
                )
            
            if not process.is_alive():
                if conn.poll(0.1):
                    return self._to_result(conn.recv())
                return ExecutionResult(success=False, error="Process died", error_type="ProcessError")
            
            if not conn.poll(min(1.0, remaining)):
                continue
            
            try:
                msg = conn.recv()
            except EOFError:
                return ExecutionResult(success=False, error="Connection lost", error_type="ProcessError")
            
            if msg["type"] == MSG_DONE:
                return self._to_result(msg)
            
            elif msg["type"] == MSG_TOOL_CALL:
                try:
                    result = mcp_client.call_tool(msg["name"], **msg.get("kwargs", {}))
                    result = self._serialize(result)
                    conn.send({"type": MSG_TOOL_RESULT, "result": result})
                except Exception as e:
                    conn.send({"type": MSG_ERROR, "error": str(e)})
            
            elif msg["type"] == MSG_LIST_TOOLS:
                try:
                    conn.send({"type": MSG_TOOL_RESULT, "result": mcp_client.list_tools()})
                except Exception as e:
                    conn.send({"type": MSG_ERROR, "error": str(e)})

    def _to_result(self, msg: dict) -> ExecutionResult:
        return ExecutionResult(
            success=msg.get("success", False),
            output=msg.get("output", ""),
            result=msg.get("result"),
            error=msg.get("error"),
            error_type=msg.get("error_type"),
            temp_files=msg.get("temp_files", []),
        )

    def _serialize(self, obj):
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [self._serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return str(obj)


def execute_code(code: str, timeout: float = 10) -> ExecutionResult:
    """Execute Python code with timeout."""
    return SandboxExecutor(timeout=timeout).execute(code)
