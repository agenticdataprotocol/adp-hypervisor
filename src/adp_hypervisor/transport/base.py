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
