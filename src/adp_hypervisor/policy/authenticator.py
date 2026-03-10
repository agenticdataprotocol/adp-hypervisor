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
Authenticator.

Defines the authentication interface (ABC) for extracting user identity
from JSON-RPC request params.
"""

import abc
from typing import Any


class Authenticator(abc.ABC):
    """Abstract interface for extracting user identity from a request.

    Implementations parse authentication credentials from JSON-RPC request
    params and return the authenticated username.

    Subclass this to integrate with different auth mechanisms
    (e.g. Bearer token, OAuth, mTLS).
    """

    @abc.abstractmethod
    def authenticate(self, params: dict[str, Any]) -> str:
        """Extract and verify user identity from request params.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The authenticated username.

        Raises:
            UnauthorizedError: If credentials are missing or malformed.
        """
