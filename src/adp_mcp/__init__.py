"""ADP-MCP Bridge: Expose ADP Hypervisor resources as MCP tools.

This package provides an MCP (Model Context Protocol) server that bridges
LLM agents to the ADP Hypervisor, translating MCP tool calls into ADP
JSON-RPC requests over a subprocess stdio transport.
"""

__all__ = [
    # Client
    "ADPClient",
    # Exceptions
    "ADPClientError",
    "ADPConnectionError",
    "ADPProtocolError",
    # Server
    "create_server",
]

from adp_mcp.client import ADPClient, ADPClientError, ADPConnectionError, ADPProtocolError
from adp_mcp.server import create_server
