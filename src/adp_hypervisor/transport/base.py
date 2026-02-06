"""
Transport layer abstract base class.

This module defines the abstract interface for ADP transports.
Transports handle the low-level message sending and receiving
over different communication channels (stdio, HTTP, etc.).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class Transport(ABC):
    """Transport layer abstract base class."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport, preparing it to send and receive messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport and release any resources."""

    @abstractmethod
    def receive(self) -> AsyncIterator[str]:
        """
        Receive messages as an async iterator of JSON strings.

        Yields:
            Raw JSON-RPC message strings.
        """

    @abstractmethod
    async def send(self, message: str) -> None:
        """
        Send a message.

        Args:
            message: The JSON string to send.
        """
