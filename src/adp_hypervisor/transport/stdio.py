"""
Stdio Transport implementation.

This module implements a newline-delimited JSON transport over
stdin/stdout for local process communication, following the
MCP (Model Context Protocol) pattern.
"""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator

from adp_hypervisor.transport.base import Transport

logger = logging.getLogger(__name__)


class StdioTransport(Transport):
    """
    Stdio-based transport using newline-delimited JSON.

    Reads JSON-RPC messages from stdin (one per line) and
    writes JSON-RPC responses to stdout (one per line).
    """

    def __init__(
        self,
        stdin: asyncio.StreamReader | None = None,
        stdout: asyncio.StreamWriter | None = None,
    ) -> None:
        """
        Initialize the StdioTransport.

        Args:
            stdin: Optional async stream reader (defaults to process stdin).
            stdout: Optional async stream writer (defaults to process stdout).
        """
        self._stdin = stdin
        self._stdout = stdout
        self._running = False

    async def start(self) -> None:
        """Start the transport by connecting to stdin/stdout streams."""
        if self._running:
            return

        if self._stdin is None:
            loop = asyncio.get_running_loop()
            self._stdin = asyncio.StreamReader()
            transport = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(self._stdin),  # type: ignore[arg-type]
                sys.stdin,
            )
            self._read_transport = transport[0]

        if self._stdout is None:
            loop = asyncio.get_running_loop()
            transport_w = await loop.connect_write_pipe(
                asyncio.BaseProtocol,
                sys.stdout,
            )
            self._stdout = asyncio.StreamWriter(
                transport_w[0],
                asyncio.BaseProtocol(),
                None,
                loop,
            )

        self._running = True
        logger.info("Stdio transport started")

    async def stop(self) -> None:
        """Stop the transport."""
        if not self._running:
            return

        self._running = False
        logger.info("Stdio transport stopped")

    async def receive(self) -> AsyncIterator[str]:
        """
        Receive newline-delimited JSON messages from stdin.

        Yields:
            Raw JSON-RPC message strings (without trailing newline).
        """
        if self._stdin is None:
            raise RuntimeError("Transport not started; call start() first")

        while self._running:
            try:
                line = await self._stdin.readline()
                if not line:
                    logger.debug("Stdin reached EOF")
                    break

                message = line.decode("utf-8").strip()
                if not message:
                    continue

                logger.debug("Received message: %s", message[:200])
                yield message

            except asyncio.CancelledError:
                logger.debug("Receive cancelled")
                break
            except Exception:
                logger.exception("Error reading from stdin")
                break

    async def send(self, message: str) -> None:
        """
        Send a newline-delimited JSON message to stdout.

        Args:
            message: The JSON string to send.
        """
        if self._stdout is None:
            raise RuntimeError("Transport not started; call start() first")

        data = message.rstrip("\n") + "\n"
        self._stdout.write(data.encode("utf-8"))
        await self._stdout.drain()
        logger.debug("Sent message: %s", message[:200])
