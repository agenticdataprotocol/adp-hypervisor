"""
Ping Handler.

Implements the adp.ping method which provides a simple health check.
"""

from typing import Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.protocol.types import EmptyResult


class PingHandler(Handler):
    """Handler for the adp.ping method.

    Returns an empty result to indicate the server is alive.
    """

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.ping"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process a ping request.

        Args:
            params: The JSON-RPC request parameters (ignored).

        Returns:
            An empty result indicating the server is alive.
        """
        return EmptyResult()
