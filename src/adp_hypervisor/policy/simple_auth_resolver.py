"""Simple Auth Resolver.

Resolves user identity using Simple Auth (username extraction only,
no password verification).
"""

import base64
import logging
from typing import Any

from adp_hypervisor.policy.role_resolver import RoleResolver, UserRoleConfig
from adp_hypervisor.protocol.errors import UnauthorizedError

logger = logging.getLogger(__name__)


class SimpleAuthResolver(RoleResolver):
    """Resolves user identity using Simple Auth.

    Extracts a username from ``_meta.authorization`` in the JSON-RPC
    request params using the format ``"Basic base64(username:password)"``.
    Only the username is used; the password is **not** verified.

    Credentials are mandatory: requests without ``_meta.authorization``
    are rejected with ``UnauthorizedError``.

    Known users are mapped to their configured role. Unknown users
    (valid credentials but username not in config) fall back to
    ``UserRoleConfig.default_role``.
    """

    def __init__(self, config: UserRoleConfig) -> None:
        """Initialize the resolver.

        Args:
            config: User-to-role mapping configuration.
        """
        self._config = config

    @property
    def default_role(self) -> str:
        """Return the default role for unknown users."""
        return self._config.default_role

    def resolve(self, params: dict[str, Any]) -> str:
        """Resolve user identity from request params to a role.

        Extracts the username from ``params["_meta"]["authorization"]``
        (Simple Auth format: ``"Basic base64(user:password)"``), then looks
        up the user's role in the config.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The role string for the resolved user, or ``default_role``
            if the user is unknown.

        Raises:
            UnauthorizedError: If credentials are missing or malformed.
        """
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            raise UnauthorizedError("Missing credentials")

        authorization = meta.get("authorization")
        if not isinstance(authorization, str) or not authorization:
            raise UnauthorizedError("Missing credentials")

        username = self._parse_simple_auth(authorization)
        if username is None:
            raise UnauthorizedError("Invalid credentials format")

        role = self._config.users.get(username)
        if role is None:
            logger.info(
                "Unknown user %r, using default role %r", username, self._config.default_role
            )
            return self._config.default_role

        logger.debug("Resolved user %r to role %r", username, role)
        return role

    def _parse_simple_auth(self, authorization: str) -> str | None:
        """Parse a Simple Auth header and extract the username.

        Expects the format ``"Basic <base64(username:password)>"``.
        The password is extracted but **not** verified.

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
