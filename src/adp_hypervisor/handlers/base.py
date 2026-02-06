"""
Handler abstract base class.

Defines the abstract interface that all ADP request handlers must implement.
Each handler processes a specific JSON-RPC method (e.g., adp.initialize, adp.ping).
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class Handler(ABC):
    """Handler abstract base class for processing ADP requests."""

    @property
    @abstractmethod
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""

    @abstractmethod
    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process a request and return the result.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            A Pydantic model representing the response.
        """
