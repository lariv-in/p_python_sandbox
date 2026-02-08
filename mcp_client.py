"""
MCP client wrapper for sandbox code execution.

Uses DIRECT tool invocation instead of HTTP to avoid deadlock when
the sandbox is called from within the MCP server.
"""

import asyncio
import inspect
import json
from typing import Any
import logging
from django.conf import settings
from django.apps import apps
from importlib import import_module

logger = logging.getLogger(__name__)


class DirectToolRegistry:
    """
    Registry that loads and calls MCP tools directly without HTTP.

    This avoids the deadlock that occurs when the sandbox (running inside
    the MCP server) tries to call back to the MCP server via HTTP.
    """

    _instance = None
    _tools: dict[str, Any] = {}
    _tool_info: dict[str, dict] = {}
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_initialized(self):
        """Lazy initialization of tool registry."""
        if self._initialized:
            return

        self._load_tools()
        self._initialized = True

    def _load_tools(self):
        """Load all tools from enabled apps."""
        for app_id in settings.ENABLED_APPS:
            try:
                # Get app config for URL prefix
                try:
                    app_config = apps.get_app_config(app_id)
                    url_prefix = getattr(app_config, "url_prefix", None)
                except LookupError:
                    continue

                if url_prefix is None:
                    continue

                # Import the tools module
                try:
                    module_name = f"{app_id}.tools"
                    mcp_module = import_module(module_name)
                except ImportError:
                    continue

                # Get the FastMCP instance
                if not hasattr(mcp_module, "get_mcp"):
                    continue

                sub_mcp = mcp_module.get_mcp()

                # Extract tools from FastMCP instance
                # FastMCP stores tools in _tool_manager.tools
                if hasattr(sub_mcp, "_tool_manager"):
                    tool_manager = sub_mcp._tool_manager
                    if hasattr(tool_manager, "_tools"):
                        for tool_name, tool in tool_manager._tools.items():
                            # Prefix tool name with url_prefix
                            full_name = f"{url_prefix}_{tool_name}"
                            self._tools[full_name] = tool
                            self._tool_info[full_name] = {
                                "name": full_name,
                                "description": getattr(tool, "description", ""),
                                "inputSchema": getattr(tool, "parameters", {}),
                            }
                            logger.debug(f"Registered tool: {full_name}")

            except Exception as e:
                logger.warning(f"Error loading tools from {app_id}: {e}")

        logger.info(f"DirectToolRegistry loaded {len(self._tools)} tools")

    def list_tools(self) -> list[dict]:
        """List all available tools."""
        self._ensure_initialized()
        return list(self._tool_info.values())

    def get_tool(self, name: str):
        """Get a tool by name."""
        self._ensure_initialized()
        return self._tools.get(name)

    def get_tool_info(self, name: str) -> dict | None:
        """Get tool info by name."""
        self._ensure_initialized()
        return self._tool_info.get(name)

    def _validate_args(self, func, kwargs: dict) -> dict:
        """Validate and convert arguments using type hints."""
        try:
            from pydantic import TypeAdapter
            import inspect
        except ImportError:
            return kwargs

        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return kwargs

        new_kwargs = kwargs.copy()

        for name, value in kwargs.items():
            if name not in sig.parameters:
                continue

            param = sig.parameters[name]
            if param.annotation == inspect.Parameter.empty:
                continue

            try:
                adapter = TypeAdapter(param.annotation)
                new_kwargs[name] = adapter.validate_python(value)
            except Exception:
                # If validation fails, pass original value
                pass

        return new_kwargs

    async def call_tool_async(self, name: str, **kwargs) -> Any:
        """Call a tool asynchronously."""
        self._ensure_initialized()

        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())[:10]}...")

        # FastMCP tools have a 'fn' attribute with the actual function
        if hasattr(tool, "fn"):
            func = tool.fn
        else:
            func = tool

        # Validate/convert arguments (e.g. dict -> Pydantic model)
        kwargs = self._validate_args(func, kwargs)

        # Call the tool
        if inspect.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = func(**kwargs)

        return result

    def call_tool_sync(self, name: str, **kwargs) -> Any:
        """Call a tool synchronously (runs async in new event loop if needed)."""
        self._ensure_initialized()

        tool = self._tools.get(name)
        if tool is None:
            available = list(self._tools.keys())[:10]
            raise ValueError(f"Tool '{name}' not found. Available: {available}...")

        # FastMCP tools have a 'fn' attribute with the actual function
        if hasattr(tool, "fn"):
            func = tool.fn
        else:
            func = tool

        # Validate/convert arguments (e.g. dict -> Pydantic model)
        kwargs = self._validate_args(func, kwargs)

        # Handle async functions
        if inspect.iscoroutinefunction(func):
            # Try to get existing event loop
            try:
                loop = asyncio.get_running_loop()
                # We're inside an async context - use nest_asyncio or run in thread
                import concurrent.futures
                import threading

                result_holder = {"result": None, "error": None}

                def run_in_thread():
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            result_holder["result"] = new_loop.run_until_complete(func(**kwargs))
                        finally:
                            new_loop.close()
                    except Exception as e:
                        result_holder["error"] = e

                thread = threading.Thread(target=run_in_thread)
                thread.start()
                thread.join(timeout=30)

                if result_holder["error"]:
                    raise result_holder["error"]
                return result_holder["result"]

            except RuntimeError:
                # No event loop running - safe to create one
                return asyncio.run(func(**kwargs))
        else:
            return func(**kwargs)


# Global registry instance
_registry = None


def get_registry() -> DirectToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = DirectToolRegistry()
    return _registry


class SandboxMCPClient:
    """
    MCP client for sandbox that uses direct tool invocation.

    This replaces the HTTP-based client to avoid deadlock.
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize the client.

        Args:
            timeout: Timeout for tool calls (used for thread join)
        """
        self.timeout = timeout
        self._registry = get_registry()

    def close(self):
        """No-op for compatibility (no HTTP connection to close)."""
        pass

    def list_tools(self) -> list[dict]:
        """List all available MCP tools."""
        return self._registry.list_tools()

    def call_tool(self, name: str, **kwargs) -> Any:
        """
        Call an MCP tool by name.

        Args:
            name: Tool name (e.g., 'students_list_student')
            **kwargs: Tool arguments

        Returns:
            Tool result
        """
        try:
            result = self._registry.call_tool_sync(name, **kwargs)
            return self._to_serializable(result)

        except Exception as e:
            raise RuntimeError(f"Tool '{name}' failed: {e}") from e

    def _to_serializable(self, obj: Any) -> Any:
        """Recursively convert Pydantic models and other objects to serializable dicts."""
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        
        # Handle Pydantic models first (before dict check, as they might be dict-like)
        if hasattr(obj, "model_dump"):
            return self._to_serializable(obj.model_dump())
        if hasattr(obj, "dict") and not isinstance(obj, dict):
            return self._to_serializable(obj.dict())
        
        if isinstance(obj, dict):
            return {k: self._to_serializable(v) for k, v in obj.items()}
        
        if isinstance(obj, (list, tuple)):
            return [self._to_serializable(x) for x in obj]
        
        if isinstance(obj, set):
            return [self._to_serializable(x) for x in obj]
        
        # Fallback: try to convert to string
        try:
            return str(obj)
        except:
            return repr(obj)

    def get_tool_info(self, name: str) -> dict | None:
        """Get information about a specific tool."""
        return self._registry.get_tool_info(name)


def create_call_tool_function(client: SandboxMCPClient):
    """
    Create the call_tool function to expose to sandbox code.
    """

    def call_tool(name: str, **kwargs) -> Any:
        """
        Call an MCP tool.

        Args:
            name: Tool name (e.g., 'filesystem_list_directory', 'students_get_student')
            **kwargs: Arguments to pass to the tool

        Returns:
            Tool result as a Python object (dict, list, or string)

        Example:
            # List all students
            students = call_tool('students_list_student')

            # Get a specific student
            student = call_tool('students_get_student', id=123)

            # Create a file
            call_tool('filesystem_create_text_file',
                     name='report.txt',
                     content='Hello World',
                     parent_path='/documents')
        """
        return client.call_tool(name, **kwargs)

    return call_tool


def create_list_tools_function(client: SandboxMCPClient):
    """
    Create the list_tools function to expose to sandbox code.
    """

    def list_tools() -> list[dict]:
        """
        List all available MCP tools.

        Returns:
            List of tool definitions with 'name', 'description', and 'inputSchema'

        Example:
            tools = list_tools()
            for tool in tools:
                print(f"{tool['name']}: {tool['description']}")
        """
        return client.list_tools()

    return list_tools
