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
Basic Auth Authenticator.

Implements HTTP Basic Auth credential extraction from JSON-RPC request params.
"""

import base64
import logging
from typing import Any

from adp_hypervisor.policy.authenticator import Authenticator
from adp_hypervisor.protocol.errors import UnauthorizedError

logger = logging.getLogger(__name__)


class BasicAuthenticator(Authenticator):
    """Authenticates users via HTTP Basic Auth.

    Extracts a username from ``_meta.authorization`` in the JSON-RPC
    request params using the format ``"Basic base64(username:password)"``.

    .. note::
        Password verification is not yet implemented. Only the username
        is extracted for role resolution.

    Credentials are mandatory: requests without ``_meta.authorization``
    are rejected with ``UnauthorizedError``.
    """

    def authenticate(self, params: dict[str, Any]) -> str:
        """Extract user identity from Basic Auth credentials.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The extracted username.

        Raises:
            UnauthorizedError: If credentials are missing or malformed.
        """
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            raise UnauthorizedError(
                "Missing credentials: set `_meta.authorization` in request params "
                "(e.g. `Basic base64(username:password)`)"
            )

        authorization = meta.get("authorization")
        if not isinstance(authorization, str) or not authorization:
            raise UnauthorizedError(
                "Missing credentials: set `_meta.authorization` in request params "
                "(e.g. `Basic base64(username:password)`)"
            )

        username = self._parse_basic_auth(authorization)
        if username is None:
            scheme, _, _ = authorization.partition(" ")
            raise UnauthorizedError(
                f"Invalid credentials format: expected `Basic base64(username:password)`, "
                f"got scheme `{scheme}`"
            )

        logger.debug("Authenticated user %r via Basic Auth", username)
        return username

    def _parse_basic_auth(self, authorization: str) -> str | None:
        """Parse a Basic Auth header and extract the username.

        Expects the format ``"Basic <base64(username:password)>"``.
        The scheme comparison is case-insensitive per RFC 7235.

        .. note::
            Password verification is not yet implemented.

        Args:
            authorization: The raw Authorization header value.

        Returns:
            The extracted username, or ``None`` if parsing fails.
        """
        scheme, _, payload = authorization.partition(" ")
        if scheme.lower() != "basic":
            return None

        encoded = payload.strip()
        if not encoded:
            return None

        # Pad base64 if needed — some clients omit trailing '='
        padded = encoded + "=" * (-len(encoded) % 4)

        try:
            decoded = base64.b64decode(padded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

        username, _, _ = decoded.partition(":")
        return username if username else None
