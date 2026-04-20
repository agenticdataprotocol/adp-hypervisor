# Copyright 2026 Datastrato, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

from adp_hypervisor.transport.base import MessageHandler, Transport

logger = logging.getLogger(__name__)


class StdioTransport(Transport):
    """
    Stdio-based transport using newline-delimited JSON.

    Reads JSON-RPC messages from stdin (one per line), dispatches each
    through the provided message handler, and writes the response to stdout.
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
        # Underlying transports for stdin/stdout pipes, used for cleanup in stop()
        self._read_transport: asyncio.BaseTransport | None = None
        self._write_transport: asyncio.BaseTransport | None = None

    async def start(self, message_handler: MessageHandler) -> None:
        """Start the transport and serve requests.

        Sets up stdin/stdout streams, then enters a message loop that
        reads lines, dispatches through *message_handler*, and writes
        responses.  Blocks until EOF or :meth:`stop` is called.

        Args:
            message_handler: Async callable that processes a JSON-RPC
                message string and returns the response string.
        """
        if self._running:
            return

        await self._setup_streams()
        self._running = True
        logger.info("Stdio transport started")

        try:
            async for message in self._receive():
                if not self._running:
                    break
                response = await message_handler(message)
                await self._send(response)
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the transport and release underlying pipe transports.

        This method is idempotent — it can be called multiple times safely,
        including after ``start()`` exits naturally (e.g. stdin EOF).
        """
        # Close the underlying transports to release the stdin/stdout pipes.
        if self._read_transport is not None:
            self._read_transport.close()
            self._read_transport = None
        if self._write_transport is not None:
            self._write_transport.close()
            self._write_transport = None

        self._running = False
        logger.info("Stdio transport stopped")

    async def _setup_streams(self) -> None:
        """Connect to stdin/stdout if not already injected."""
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
            write_protocol = asyncio.streams.FlowControlMixin()
            transport_w = await loop.connect_write_pipe(
                lambda: write_protocol,
                sys.stdout,
            )
            self._write_transport = transport_w[0]
            self._stdout = asyncio.StreamWriter(
                self._write_transport,
                write_protocol,
                None,
                loop,
            )

    async def _receive(self) -> AsyncIterator[str]:
        """Receive newline-delimited JSON messages from stdin.

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

    async def _send(self, message: str) -> None:
        """Send a newline-delimited JSON message to stdout.

        Args:
            message: The JSON string to send.
        """
        if self._stdout is None:
            raise RuntimeError("Transport not started; call start() first")

        data = message.rstrip("\n") + "\n"
        self._stdout.write(data.encode("utf-8"))
        await self._stdout.drain()
        logger.debug("Sent message: %s", message[:200])
