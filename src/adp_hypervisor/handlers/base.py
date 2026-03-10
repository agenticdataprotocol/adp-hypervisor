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
