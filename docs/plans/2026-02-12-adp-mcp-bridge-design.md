# Design: ADP-MCP Bridge (`adp_mcp`)

## Problem Statement

LLM agents (Claude Desktop, Cursor, VS Code Copilot, etc.) use the
**Model Context Protocol (MCP)** to interact with external data sources and
tools. The `adp_hypervisor` server exposes data through the **ADP JSON-RPC
protocol** over stdio, but LLM agents cannot connect to it directly because
they speak MCP, not ADP.

We need a bridge package that translates between MCP and ADP so that any
MCP-compatible LLM agent can discover, describe, validate, and execute data
operations against ADP-managed resources—**without modifying the
`adp_hypervisor` package**.

## Proposed Approach

Create a new package `src/adp_mcp/` that acts as both an **MCP Server** (facing
the LLM) and an **ADP Client** (facing the hypervisor). It spawns
`adp_hypervisor` as a subprocess and communicates via newline-delimited
JSON-RPC over stdio.

## Architecture

```
┌─────────────────┐      stdio (MCP)       ┌──────────────────┐      stdio (ADP JSON-RPC)      ┌──────────────────┐
│   LLM Agent     │ ◄────────────────────► │    adp_mcp       │ ◄────────────────────────────► │  adp_hypervisor  │
│ (Claude Desktop │                         │  ┌────────────┐  │                                │    (ADP Server)  │
│  Cursor, etc.)  │                         │  │ MCP Server │  │     subprocess spawn           │                  │
│                 │                         │  │ (FastMCP)  │  │     & lifecycle mgmt           │                  │
│   MCP Client    │                         │  ├────────────┤  │                                │                  │
│                 │                         │  │ ADP Client │  │                                │                  │
│                 │                         │  └────────────┘  │                                │                  │
└─────────────────┘                         └──────────────────┘                               └──────────────────┘
```

### Data Flow (example: QUERY)

1. LLM calls MCP tool `adp_execute` with `resource_id` and `intent` dict.
2. `adp_mcp` wraps params into a JSON-RPC `adp.execute` request envelope.
3. Sends the request to `adp_hypervisor` subprocess via stdin.
4. Reads the JSON-RPC response from subprocess stdout.
5. Extracts `result`, serializes to JSON string, returns to LLM.

### Typical LLM Workflow

```
discover  →  describe  →  (validate)  →  execute
   │              │             │             │
   ▼              ▼             ▼             ▼
 List all     Get schema    Pre-check     Run LOOKUP/
 resources    & capabilities  intent IR    QUERY/INGEST/
                                           REVISE
```

## Package Structure

```
src/adp_mcp/
├── __init__.py          # Package entry, defines __all__
├── __main__.py          # CLI entry: python -m adp_mcp --config <dir>
├── client.py            # ADPClient: subprocess mgmt + JSON-RPC communication
└── server.py            # MCP Server: FastMCP with 4 tools bridging to ADPClient
```

### Module Responsibilities

| Module          | Responsibility |
|-----------------|----------------|
| `__init__.py`   | Re-exports `ADPClient` and package metadata |
| `__main__.py`   | Parse CLI args (`--config`), start MCP server with lifespan |
| `client.py`     | `ADPClient` class: spawn subprocess, initialize handshake, send JSON-RPC requests, manage lifecycle |
| `server.py`     | Create `FastMCP` instance, register 4 tools, bridge to `ADPClient` |

### Dependency Principle

- `adp_mcp` depends **only** on the `mcp` Python SDK.
- It does **not** import any code from `adp_hypervisor`.
- It communicates with `adp_hypervisor` exclusively through the subprocess
  stdio transport and the ADP JSON-RPC protocol.

## Detailed Design

### ADPClient (`client.py`)

```python
class ADPClient:
    """ADP JSON-RPC client that communicates with adp_hypervisor via subprocess."""

    # --- public methods ---

    async def start(self, config_path: str) -> None:
        """Spawn adp_hypervisor subprocess and perform initialize handshake.

        Args:
            config_path: Path to the ADP manifest directory.

        Raises:
            ADPConnectionError: If the subprocess fails to start.
            ADPProtocolError: If the initialize handshake fails.
        """

    async def stop(self) -> None:
        """Gracefully terminate the adp_hypervisor subprocess."""

    async def discover(
        self,
        domain_prefix: str | None = None,
        intent_class: str | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        """Send adp.discover and return the result dict."""

    async def describe(
        self,
        resource_id: str,
        intent_class: str,
        version: int | None = None,
        cursor: str | None = None,
    ) -> dict:
        """Send adp.describe and return the result dict."""

    async def validate(
        self,
        resource_id: str,
        intent: dict,
    ) -> dict:
        """Send adp.validate and return the result dict."""

    async def execute(
        self,
        resource_id: str,
        intent: dict,
        cursor: str | None = None,
    ) -> dict:
        """Send adp.execute and return the result dict."""

    # --- private methods ---

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and read the response.

        1. Construct JSON-RPC 2.0 envelope with auto-incrementing id.
        2. Serialize to JSON + newline, write to subprocess stdin.
        3. Read one line from subprocess stdout.
        4. Parse JSON-RPC response.
        5. If response contains 'error', raise ADPProtocolError.
        6. Return the 'result' dict.
        """

    async def _ensure_alive(self) -> None:
        """Check subprocess health; attempt restart if dead (max 3 retries)."""
```

**Implementation details:**

- Uses `asyncio.create_subprocess_exec` with `stdin=PIPE, stdout=PIPE,
  stderr=PIPE` to spawn `python -m adp_hypervisor --config <path>`.
- Request IDs are auto-incrementing integers.
- `start()` sends `adp.initialize` with client info
  `{"name": "adp-mcp-bridge", "version": "0.1.0"}` and validates the protocol
  version in the response.
- `stop()` sends SIGTERM, waits up to 5s, then SIGKILL if needed.

### MCP Server (`server.py`)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("adp-mcp-bridge", lifespan=app_lifespan)

@mcp.tool()
async def adp_discover(
    domain_prefix: str | None = None,
    intent_class: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
) -> str:
    """Discover available ADP resources.

    Returns a JSON list of resources with their IDs, supported intent classes,
    and descriptions. Use filters to narrow results.

    Args:
        domain_prefix: Filter resources by domain prefix (e.g., "posix_demo").
        intent_class: Filter by intent class (LOOKUP, QUERY, INGEST, REVISE).
        keyword: Keyword search across resource metadata.
        cursor: Pagination cursor from a previous response.
    """

@mcp.tool()
async def adp_describe(
    resource_id: str,
    intent_class: str,
    version: int | None = None,
    cursor: str | None = None,
) -> str:
    """Describe an ADP resource's usage contract.

    Returns the resource's field schema, predicate capabilities, projection
    options, and mutable fields for a specific intent class.

    Args:
        resource_id: Resource identifier in "domain:alias" format.
        intent_class: The intent class to describe (LOOKUP, QUERY, INGEST, REVISE).
        version: Specific resource version (defaults to latest).
        cursor: Pagination cursor for large field lists.
    """

@mcp.tool()
async def adp_validate(
    resource_id: str,
    intent: dict,
) -> str:
    """Validate an intent IR against a resource's schema before execution.

    Returns validation result indicating whether the intent is valid, with
    detailed error information if validation fails. Use this before execute
    to catch issues early.

    Args:
        resource_id: Target resource identifier in "domain:alias" format.
        intent: The intent IR dict following the ADP Intent specification.
    """

@mcp.tool()
async def adp_execute(
    resource_id: str,
    intent: dict,
    cursor: str | None = None,
) -> str:
    """Execute an ADP intent against a resource.

    Supports four intent classes:
    - LOOKUP: Retrieve a single entity by unique key.
    - QUERY: Retrieve a set of entities using predicates, projections, ordering.
    - INGEST: Create or append new data.
    - REVISE: Update or delete existing data.

    Use adp_describe first to understand the resource's schema and capabilities,
    then construct the intent IR accordingly.

    Args:
        resource_id: Target resource identifier in "domain:alias" format.
        intent: The intent IR dict following the ADP Intent specification.
        cursor: Pagination cursor for large result sets.
    """
```

All tools return JSON-serialized strings so that the LLM can parse and
reason about structured data.

### Lifespan Management

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Manage ADPClient lifecycle tied to MCP server startup/shutdown."""
    client = ADPClient()
    await client.start(config_path)
    try:
        yield {"client": client}
    finally:
        await client.stop()
```

The `lifespan` context manager ensures the ADP subprocess is always
cleaned up, regardless of how the MCP server exits (normal shutdown,
exception, or signal).

### CLI Entry Point (`__main__.py`)

```python
"""CLI entry point for the ADP-MCP bridge server."""

import argparse
from adp_mcp.server import create_server

def main() -> None:
    parser = argparse.ArgumentParser(description="ADP-MCP Bridge Server")
    parser.add_argument("--config", required=True, help="Path to ADP manifest directory")
    args = parser.parse_args()

    server = create_server(args.config)
    server.run(transport="stdio")

if __name__ == "__main__":
    main()
```

**Usage:**

```bash
# Direct invocation
python -m adp_mcp --config examples/conf

# Or via installed script
adp-mcp --config examples/conf
```

## Error Handling

### Custom Exceptions

```python
class ADPClientError(Exception):
    """Base error for ADP client operations."""

class ADPConnectionError(ADPClientError):
    """Failed to connect to or communicate with adp_hypervisor subprocess."""

class ADPProtocolError(ADPClientError):
    """ADP server returned a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(f"ADP error {code}: {message}")
        self.code = code
        self.data = data
```

### Error Scenarios

| Scenario | Handling |
|----------|----------|
| Subprocess fails to start | Raise `ADPConnectionError`, MCP server terminates |
| Initialize handshake fails | Raise `ADPProtocolError`, MCP server terminates |
| JSON-RPC error response | Convert to `McpError`, returned as tool error to LLM |
| Subprocess unexpected exit | Auto-restart (max 3 attempts), then terminate |
| Request timeout (30s) | Return timeout error to LLM |
| MCP server shutdown | Send SIGTERM to subprocess, wait 5s, SIGKILL if needed |

## Configuration

### pyproject.toml Changes

```toml
[project.optional-dependencies]
mcp = ["mcp[cli]>=1.0"]

[project.scripts]
adp-mcp = "adp_mcp.__main__:main"
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "adp-hypervisor": {
      "command": "python",
      "args": ["-m", "adp_mcp", "--config", "/path/to/examples/conf"],
      "env": {
        "PG_PASSWORD": "adp_pass"
      }
    }
  }
}
```

### Cursor / VS Code Configuration

```json
{
  "mcp": {
    "servers": {
      "adp-hypervisor": {
        "command": "python",
        "args": ["-m", "adp_mcp", "--config", "/path/to/examples/conf"]
      }
    }
  }
}
```

## Workplan

- [ ] Create `src/adp_mcp/__init__.py` with `__all__` and package metadata
- [ ] Create `src/adp_mcp/client.py` with `ADPClient` class
  - [ ] Subprocess spawn and lifecycle management
  - [ ] JSON-RPC request/response communication
  - [ ] Initialize handshake
  - [ ] Auto-restart on subprocess death
  - [ ] Custom exception classes
- [ ] Create `src/adp_mcp/server.py` with FastMCP tools
  - [ ] `adp_discover` tool
  - [ ] `adp_describe` tool
  - [ ] `adp_validate` tool
  - [ ] `adp_execute` tool
  - [ ] Lifespan management
- [ ] Create `src/adp_mcp/__main__.py` CLI entry point
- [ ] Update `pyproject.toml` with optional mcp dependency and script entry
- [ ] Add tests for ADPClient (mock subprocess)
- [ ] Add tests for MCP tools (integration)
- [ ] Update documentation (README, examples)
- [ ] End-to-end validation with Claude Desktop or MCP inspector
