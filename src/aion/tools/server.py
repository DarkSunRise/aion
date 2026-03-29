"""
In-process MCP server factory for Aion tools.

Creates a McpSdkServerConfig that plugs directly into ClaudeAgentOptions.mcp_servers.
No subprocess, no IPC — tools run in the same process with direct access to
MemoryStore and SessionDB instances.
"""

from claude_agent_sdk import create_sdk_mcp_server

from aion.memory.store import MemoryStore
from aion.memory.sessions import SessionDB
from .mcp_tools import create_aion_tools


def create_aion_mcp_server(memory: MemoryStore, sessions: SessionDB):
    """Create an in-process MCP server with all Aion tools.

    Returns a McpSdkServerConfig ready for ClaudeAgentOptions.mcp_servers.
    """
    tools = create_aion_tools(memory, sessions)
    return create_sdk_mcp_server("aion", version="0.2.0", tools=tools)
