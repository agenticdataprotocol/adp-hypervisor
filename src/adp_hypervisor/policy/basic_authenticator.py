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
            raise UnauthorizedError("Missing credentials")

        authorization = meta.get("authorization")
        if not isinstance(authorization, str) or not authorization:
            raise UnauthorizedError("Missing credentials")

        username = self._parse_basic_auth(authorization)
        if username is None:
            raise UnauthorizedError("Invalid credentials format")

        logger.debug("Authenticated user %r via Basic Auth", username)
        return username

    def _parse_basic_auth(self, authorization: str) -> str | None:
        """Parse a Basic Auth header and extract the username.

        Expects the format ``"Basic <base64(username:password)>"``.

        .. note::
            Password verification is not yet implemented.

        Args:
            authorization: The raw Authorization header value.

        Returns:
            The extracted username, or ``None`` if parsing fails.
        """
        if not authorization.startswith("Basic "):
            return None

        encoded = authorization[6:].strip()
        if not encoded:
            return None

        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

        username, _, _ = decoded.partition(":")
        return username if username else None
