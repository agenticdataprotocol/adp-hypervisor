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

"""Tests for the Stdio Transport."""

import asyncio
import json
import unittest

from adp_hypervisor.transport.stdio import StdioTransport

# =============================================================================
# Helpers
# =============================================================================


async def _noop_handler(msg: str) -> str:
    """No-op message handler that returns an empty JSON object."""
    return "{}"


def _make_streams() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Create a connected StreamReader/StreamWriter pair for testing."""
    reader = asyncio.StreamReader()

    # Use a simple in-memory transport for the writer
    write_transport = _MemoryWriteTransport()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    writer = asyncio.StreamWriter(write_transport, protocol, reader, loop)

    return reader, writer


class _MemoryWriteTransport(asyncio.Transport):
    """In-memory write transport that captures written bytes."""

    def __init__(self) -> None:
        super().__init__()
        self.buffer = bytearray()
        self._closing = False

    def write(self, data: bytes) -> None:  # type: ignore[override]
        self.buffer.extend(data)

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    def get_extra_info(self, name: str, default: object = None) -> object:
        return default


# =============================================================================
# Transport Lifecycle Tests
# =============================================================================


class TestStdioTransportLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests for transport start/stop behavior."""

    async def test_start_with_injected_streams(self) -> None:
        reader, writer = _make_streams()
        reader.feed_eof()
        transport = StdioTransport(stdin=reader, stdout=writer)
        await transport.start(_noop_handler)
        # start() blocks until EOF, then sets _running = False in finally
        self.assertFalse(transport._running)

    async def test_start_is_idempotent(self) -> None:
        reader, writer = _make_streams()
        transport = StdioTransport(stdin=reader, stdout=writer)

        task = asyncio.create_task(transport.start(_noop_handler))
        for _ in range(50):
            if transport._running:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(transport._running)

        # Second call returns immediately because _running is already True
        await transport.start(_noop_handler)
        self.assertTrue(transport._running)

        reader.feed_eof()
        await task

    async def test_stop(self) -> None:
        reader, writer = _make_streams()
        transport = StdioTransport(stdin=reader, stdout=writer)

        task = asyncio.create_task(transport.start(_noop_handler))
        for _ in range(50):
            if transport._running:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(transport._running)

        await transport.stop()
        # Feed EOF to unblock readline so the message loop can exit
        reader.feed_eof()
        await task
        self.assertFalse(transport._running)

    async def test_stop_when_not_started(self) -> None:
        reader, writer = _make_streams()
        transport = StdioTransport(stdin=reader, stdout=writer)
        await transport.stop()
        self.assertFalse(transport._running)


# =============================================================================
# Send Tests
# =============================================================================


class TestStdioTransportSend(unittest.IsolatedAsyncioTestCase):
    """Tests for sending messages."""

    async def _setup_transport(
        self,
    ) -> tuple[StdioTransport, _MemoryWriteTransport]:
        """Create a transport with injected streams ready for _send() calls."""
        reader, writer = _make_streams()
        mem_transport: _MemoryWriteTransport = writer.transport  # type: ignore[assignment]
        transport = StdioTransport(stdin=reader, stdout=writer)
        await transport._setup_streams()
        transport._running = True
        return transport, mem_transport

    async def test_send_appends_newline(self) -> None:
        transport, mem = await self._setup_transport()

        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        await transport._send(msg)

        output = mem.buffer.decode("utf-8")
        self.assertTrue(output.endswith("\n"))
        self.assertEqual(output.strip(), msg)

    async def test_send_strips_extra_trailing_newline(self) -> None:
        transport, mem = await self._setup_transport()

        msg = '{"jsonrpc":"2.0","id":1,"result":{}}\n'
        await transport._send(msg)

        output = mem.buffer.decode("utf-8")
        # Should have exactly one trailing newline, not two
        self.assertEqual(output, '{"jsonrpc":"2.0","id":1,"result":{}}\n')

    async def test_send_without_start_raises(self) -> None:
        transport = StdioTransport()
        with self.assertRaisesRegex(RuntimeError, "Transport not started"):
            await transport._send("test")

    async def test_send_multiple_messages(self) -> None:
        transport, mem = await self._setup_transport()

        messages = [json.dumps({"jsonrpc": "2.0", "id": i, "result": {}}) for i in range(3)]
        for msg in messages:
            await transport._send(msg)

        output = mem.buffer.decode("utf-8")
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines):
            self.assertEqual(json.loads(line)["id"], i)


# =============================================================================
# Receive Tests
# =============================================================================


class TestStdioTransportReceive(unittest.IsolatedAsyncioTestCase):
    """Tests for receiving messages."""

    async def _setup_transport(self) -> tuple[StdioTransport, asyncio.StreamReader]:
        """Create a transport with injected streams ready for _receive() calls."""
        reader, writer = _make_streams()
        transport = StdioTransport(stdin=reader, stdout=writer)
        await transport._setup_streams()
        transport._running = True
        return transport, reader

    async def test_receive_single_message(self) -> None:
        transport, reader = await self._setup_transport()

        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test"})
        reader.feed_data((msg + "\n").encode("utf-8"))
        reader.feed_eof()

        received: list[str] = []
        async for message in transport._receive():
            received.append(message)

        self.assertEqual(len(received), 1)
        self.assertEqual(json.loads(received[0])["method"], "test")

    async def test_receive_multiple_messages(self) -> None:
        transport, reader = await self._setup_transport()

        messages = [
            json.dumps({"jsonrpc": "2.0", "id": i, "method": f"test.{i}"}) for i in range(3)
        ]
        data = "\n".join(messages) + "\n"
        reader.feed_data(data.encode("utf-8"))
        reader.feed_eof()

        received: list[str] = []
        async for message in transport._receive():
            received.append(message)

        self.assertEqual(len(received), 3)
        for i, msg in enumerate(received):
            self.assertEqual(json.loads(msg)["method"], f"test.{i}")

    async def test_receive_skips_empty_lines(self) -> None:
        transport, reader = await self._setup_transport()

        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test"})
        data = f"\n\n{msg}\n\n"
        reader.feed_data(data.encode("utf-8"))
        reader.feed_eof()

        received: list[str] = []
        async for message in transport._receive():
            received.append(message)

        self.assertEqual(len(received), 1)

    async def test_receive_handles_eof(self) -> None:
        transport, reader = await self._setup_transport()

        reader.feed_eof()

        received: list[str] = []
        async for message in transport._receive():
            received.append(message)

        self.assertEqual(len(received), 0)

    async def test_receive_without_start_raises(self) -> None:
        transport = StdioTransport()
        with self.assertRaisesRegex(RuntimeError, "Transport not started"):
            async for _ in transport._receive():
                pass

    async def test_receive_stops_when_transport_stopped(self) -> None:
        transport, reader = await self._setup_transport()

        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test"})
        reader.feed_data((msg + "\n").encode("utf-8"))

        received: list[str] = []
        async for message in transport._receive():
            received.append(message)
            await transport.stop()

        self.assertEqual(len(received), 1)


# =============================================================================
# Round-trip Tests
# =============================================================================


class TestStdioTransportRoundTrip(unittest.IsolatedAsyncioTestCase):
    """Tests for full send/receive round-trip."""

    async def test_start_processes_and_responds(self) -> None:
        """Verify that start() receives messages, dispatches to handler, and sends responses."""
        reader, writer = _make_streams()
        write_transport: _MemoryWriteTransport = writer.transport  # type: ignore[assignment]
        transport = StdioTransport(stdin=reader, stdout=writer)

        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "adp.ping"})
        reader.feed_data((msg + "\n").encode("utf-8"))
        reader.feed_eof()

        async def echo_handler(message: str) -> str:
            return message

        await transport.start(echo_handler)

        output = write_transport.buffer.decode("utf-8").strip()
        parsed = json.loads(output)
        self.assertEqual(parsed["method"], "adp.ping")
