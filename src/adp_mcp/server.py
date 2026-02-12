"""MCP Server module exposing ADP Hypervisor resources as MCP tools.

Uses FastMCP to register four tools (discover, describe, validate, execute)
that bridge MCP tool calls to the ADP JSON-RPC client.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from adp_mcp.client import ADPClient, ADPClientError

logger = logging.getLogger(__name__)


def create_server(config_path: str) -> FastMCP:
    """Create and configure the MCP server with ADP bridge tools.

    Args:
        config_path: Path to the ADP manifest directory.

    Returns:
        A configured FastMCP instance ready to run.
    """

    @asynccontextmanager
    async def app_lifespan(server: FastMCP) -> AsyncIterator[dict[str, ADPClient]]:
        """Manage ADPClient lifecycle tied to MCP server startup/shutdown.

        Args:
            server: The FastMCP server instance.

        Yields:
            A dict containing the initialized ADPClient.
        """
        client = ADPClient()
        await client.start(config_path)
        try:
            yield {"client": client}
        finally:
            await client.stop()

    mcp = FastMCP("adp-mcp-bridge", lifespan=app_lifespan)

    @mcp.tool()
    async def adp_discover(
        domain_prefix: str | None = None,
        intent_class: str | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        ctx: Context = None,  # type: ignore[assignment, type-arg]
    ) -> str:
        """Discover available ADP resources.

        Returns a JSON list of resources with their IDs, supported intent classes,
        and descriptions. Use filters to narrow results.

        Args:
            domain_prefix: Filter resources by domain prefix (e.g., "posix_demo").
            intent_class: Filter by intent class (LOOKUP, QUERY, INGEST, REVISE).
            keyword: Keyword search across resource metadata.
            cursor: Pagination cursor from a previous response.
            ctx: MCP request context injected by FastMCP.

        Returns:
            JSON-serialized discovery results.

        Raises:
            McpError: If the ADP client operation fails.
        """
        client: ADPClient = ctx.request_context.lifespan_context["client"]
        try:
            result = await client.discover(
                domain_prefix=domain_prefix,
                intent_class=intent_class,
                keyword=keyword,
                cursor=cursor,
            )
        except ADPClientError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e))) from e
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def adp_describe(
        resource_id: str,
        intent_class: str,
        version: int | None = None,
        cursor: str | None = None,
        ctx: Context = None,  # type: ignore[assignment, type-arg]
    ) -> str:
        """Describe an ADP resource's usage contract.

        Returns the resource's field schema, predicate capabilities, projection
        options, and mutable fields for a specific intent class.

        Args:
            resource_id: Resource identifier in "domain:alias" format.
            intent_class: The intent class to describe (LOOKUP, QUERY, INGEST, REVISE).
            version: Specific resource version (defaults to latest).
            cursor: Pagination cursor for large field lists.
            ctx: MCP request context injected by FastMCP.

        Returns:
            JSON-serialized description results.

        Raises:
            McpError: If the ADP client operation fails.
        """
        client: ADPClient = ctx.request_context.lifespan_context["client"]
        try:
            result = await client.describe(
                resource_id=resource_id,
                intent_class=intent_class,
                version=version,
                cursor=cursor,
            )
        except ADPClientError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e))) from e
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def adp_validate(
        resource_id: str,
        intent: dict[str, object],
        ctx: Context = None,  # type: ignore[assignment, type-arg]
    ) -> str:
        """Validate an intent IR against a resource's schema before execution.

        Returns validation result indicating whether the intent is valid, with
        detailed error information if validation fails.

        Args:
            resource_id: Target resource identifier in "domain:alias" format.
            intent: The intent IR dict following the ADP Intent specification.
            ctx: MCP request context injected by FastMCP.

        Returns:
            JSON-serialized validation results.

        Raises:
            McpError: If the ADP client operation fails.
        """
        client: ADPClient = ctx.request_context.lifespan_context["client"]
        try:
            result = await client.validate(
                resource_id=resource_id,
                intent=intent,
            )
        except ADPClientError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e))) from e
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def adp_execute(
        resource_id: str,
        intent: dict[str, object],
        cursor: str | None = None,
        ctx: Context = None,  # type: ignore[assignment, type-arg]
    ) -> str:
        """Execute an ADP intent (LOOKUP/QUERY/INGEST/REVISE) against a resource.

        Use adp_describe first to understand the resource's schema and capabilities,
        then construct the intent IR accordingly.

        Args:
            resource_id: Target resource identifier in "domain:alias" format.
            intent: The intent IR dict following the ADP Intent specification.
            cursor: Pagination cursor for large result sets.
            ctx: MCP request context injected by FastMCP.

        Returns:
            JSON-serialized execution results.

        Raises:
            McpError: If the ADP client operation fails.
        """
        client: ADPClient = ctx.request_context.lifespan_context["client"]
        try:
            result = await client.execute(
                resource_id=resource_id,
                intent=intent,
                cursor=cursor,
            )
        except ADPClientError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e))) from e
        return json.dumps(result, indent=2)

    return mcp
