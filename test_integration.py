#!/usr/bin/env python
"""
Integration test for Python sandbox.

This tests the sandbox as it would be called by the AI orchestrator,
including calling other MCP tools from within the sandbox.

Run with: uv run python manage.py test p_python_sandbox.test_integration
"""

import os
import sys

# Setup Django if not already
if 'django' not in sys.modules:
    # Add parent dir to path for imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lariv.settings')
    import django
    django.setup()

from plugins.p_python_sandbox.tools import get_mcp
from plugins.p_python_sandbox.mcp_client import SandboxMCPClient, get_registry


def test_direct_executor():
    """Test the executor directly."""
    print("\n" + "="*60)
    print("TEST 1: Direct executor test")
    print("="*60)
    
    from plugins.p_python_sandbox.executor import execute_code
    
    # Basic test
    r = execute_code("result = 2 + 2")
    print(f"  2+2 = {r.result} (success: {r.success})")
    assert r.success and r.result == 4, f"Basic test failed: {r.error}"
    
    # Import test
    r = execute_code("import json; result = json.dumps({'a': 1})")
    print(f"  json.dumps = {r.result} (success: {r.success})")
    assert r.success, f"Import test failed: {r.error}"
    
    print("  ✓ Direct executor works")


def test_tool_registry():
    """Test that tools are loaded into the registry."""
    print("\n" + "="*60)
    print("TEST 2: Tool registry test")
    print("="*60)
    
    registry = get_registry()
    tools = registry.list_tools()
    
    print(f"  Loaded {len(tools)} tools")
    
    # Show first 10 tools
    for t in tools[:10]:
        print(f"    - {t['name']}")
    
    if len(tools) > 10:
        print(f"    ... and {len(tools) - 10} more")
    
    assert len(tools) > 0, "No tools loaded!"
    print("  ✓ Tool registry works")


def test_direct_tool_call():
    """Test calling a tool directly through the registry."""
    print("\n" + "="*60)
    print("TEST 3: Direct tool call test")
    print("="*60)
    
    client = SandboxMCPClient()
    
    # Try filesystem_list_directory which doesn't require special params
    tool_name = 'filesystem_list_directory'
    print(f"  Calling: {tool_name}")
    
    try:
        # Tools require input_model parameter
        result = client.call_tool(tool_name, path=None)
        print(f"  Result type: {type(result).__name__}")
        if isinstance(result, dict):
            print(f"  Keys: {list(result.keys())[:5]}")
        elif isinstance(result, list):
            print(f"  Length: {len(result)}")
        print("  ✓ Direct tool call works")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise


def test_sandbox_calling_tools():
    """Test sandbox code that calls MCP tools."""
    print("\n" + "="*60)
    print("TEST 4: Sandbox calling MCP tools")
    print("="*60)
    
    from plugins.p_python_sandbox.executor import execute_code
    
    # First, list available tools from within sandbox
    code = """
tools = list_tools()
result = {
    'count': len(tools),
    'first_5': [t['name'] for t in tools[:5]]
}
"""
    r = execute_code(code, timeout=30)
    print(f"  list_tools() success: {r.success}")
    if r.success:
        print(f"  Found {r.result['count']} tools: {r.result['first_5']}")
    else:
        print(f"  Error: {r.error}")
        raise AssertionError(f"list_tools failed: {r.error}")
    
    # Now try calling filesystem_list_directory
    print(f"  Testing call_tool('filesystem_list_directory')")
    
    code = """
result = call_tool('filesystem_list_directory', path=None)
"""
    r = execute_code(code, timeout=30)
    print(f"  call_tool() success: {r.success}")
    if r.success:
        if isinstance(r.result, dict):
            print(f"  Result keys: {list(r.result.keys())[:5]}")
        else:
            print(f"  Result type: {type(r.result).__name__}")
    else:
        print(f"  Error: {r.error}")
        raise AssertionError(f"call_tool failed: {r.error}")
    
    print("  ✓ Sandbox can call tools")


def test_mcp_tool_interface():
    """Test the MCP tool interface (as the orchestrator would call it)."""
    print("\n" + "="*60)
    print("TEST 5: MCP tool interface test")
    print("="*60)
    
    mcp = get_mcp()
    
    # Get the execute_python tool
    tool_manager = mcp._tool_manager
    tools = tool_manager._tools
    
    print(f"  Python sandbox exposes {len(tools)} tools:")
    for name in tools:
        print(f"    - {name}")
    
    # Call execute_python directly
    execute_python = tools.get('execute_python')
    if execute_python:
        print("\n  Calling execute_python tool:")
        
        code = """
import math
result = {
    'pi': math.pi,
    'sqrt_2': math.sqrt(2),
    'message': 'Hello from sandbox!'
}
"""
        # The tool function
        fn = execute_python.fn
        result = fn(code=code, timeout=10)
        
        print(f"    success: {result.success}")
        print(f"    result: {result.result}")
        if result.error:
            print(f"    error: {result.error}")
        
        assert result.success, f"execute_python failed: {result.error}"
    
    print("  ✓ MCP tool interface works")


def test_complex_sandbox_code():
    """Test complex sandbox code with loops and tool calls."""
    print("\n" + "="*60)
    print("TEST 6: Complex sandbox code")
    print("="*60)
    
    from plugins.p_python_sandbox.executor import execute_code
    
    code = """
import json

# Get list of tools
tools = list_tools()
tool_names = [t['name'] for t in tools]

# Filter to find list tools
list_tool_names = [n for n in tool_names if 'list' in n.lower()]

# Build a report
report = []
report.append(f"Total tools: {len(tools)}")
report.append(f"List tools: {len(list_tool_names)}")
report.append("")
report.append("First 5 list tools:")
for name in list_tool_names[:5]:
    report.append(f"  - {name}")

result = {
    'report': '\\n'.join(report),
    'tool_count': len(tools),
    'list_tool_count': len(list_tool_names)
}
"""
    r = execute_code(code, timeout=30)
    
    print(f"  Success: {r.success}")
    if r.success:
        print(f"  Tool count: {r.result['tool_count']}")
        print(f"  List tool count: {r.result['list_tool_count']}")
        print("\n  Report:")
        for line in r.result['report'].split('\n'):
            print(f"    {line}")
    else:
        print(f"  Error: {r.error}")
        raise AssertionError(f"Complex code failed: {r.error}")
    
    print("  ✓ Complex sandbox code works")


def main():
    print("\n" + "#"*60)
    print("# PYTHON SANDBOX INTEGRATION TESTS")
    print("#"*60)
    
    try:
        test_direct_executor()
        test_tool_registry()
        test_direct_tool_call()
        test_sandbox_calling_tools()
        test_mcp_tool_interface()
        test_complex_sandbox_code()
        
        print("\n" + "="*60)
        print("ALL TESTS PASSED ✓")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
