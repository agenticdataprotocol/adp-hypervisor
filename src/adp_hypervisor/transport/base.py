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
Transport layer abstract base class.

This module defines the abstract interface for ADP transports.
Transports handle the low-level message sending and receiving
over different communication channels (stdio, HTTP, etc.).
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

MessageHandler = Callable[[str], Awaitable[str]]
"""Async callable that processes a JSON-RPC message and returns a response."""


class Transport(ABC):
    """Transport layer abstract base class.

    Each transport implementation owns its serve loop.  The server calls
    ``start(message_handler)`` which blocks until the transport is stopped.
    """

    @abstractmethod
    async def start(self, message_handler: MessageHandler) -> None:
        """Start the transport and serve requests.

        The method should block until :meth:`stop` is called or the
        transport reaches a natural end (e.g. stdin EOF).

        Args:
            message_handler: Async callable that accepts a raw JSON-RPC
                message string and returns the response string.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport and release any resources."""
