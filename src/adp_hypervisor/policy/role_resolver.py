"""
Role Resolver.

Extracts user identity from request metadata and resolves it to a role
using a server-side user-to-role configuration.
"""

import base64
import logging
from typing import Any

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import ADPModel

logger = logging.getLogger(__name__)


class UserRoleConfig(ADPModel):
    """Configuration for user-to-role mapping.

    Loaded from ``users.yaml`` at server startup. Maps usernames to roles
    and provides a default role for unauthenticated or unknown users.
    """

    default_role: str = PydanticField(
        default="default",
        description="Role assigned to unauthenticated or unknown users",
    )
    users: dict[str, str] = PydanticField(
        default_factory=dict,
        description="Mapping of username to role (e.g. {'admin': 'admin', 'alice': 'analyst'})",
    )


class RoleResolver:
    """Resolves user identity from request params to a role.

    Parses Basic Auth credentials from ``_meta.authorization`` in the
    JSON-RPC request params, extracts the username, and looks up the
    corresponding role from the server-side ``UserRoleConfig``.

    When no credentials are provided or the user is unknown, falls back
    to ``UserRoleConfig.default_role``.
    """

    def __init__(self, config: UserRoleConfig) -> None:
        """Initialize the resolver.

        Args:
            config: User-to-role mapping configuration.
        """
        self._config = config

    @property
    def default_role(self) -> str:
        """Return the default role for unauthenticated/unknown users."""
        return self._config.default_role

    def resolve(self, params: dict[str, Any]) -> str:
        """Resolve user identity from request params to a role.

        Extracts the username from ``params["_meta"]["authorization"]``
        (Basic Auth format: ``"Basic base64(user:password)"``), then looks
        up the user's role in the config.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The role string for the resolved user, or ``default_role``
            if no credentials are provided or the user is unknown.
        """
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            return self._config.default_role

        authorization = meta.get("authorization")
        if not isinstance(authorization, str) or not authorization:
            return self._config.default_role

        username = self._parse_basic_auth(authorization)
        if username is None:
            logger.warning("Failed to parse authorization header, using default role")
            return self._config.default_role

        role = self._config.users.get(username)
        if role is None:
            logger.info(
                "Unknown user %r, using default role %r", username, self._config.default_role
            )
            return self._config.default_role

        logger.debug("Resolved user %r to role %r", username, role)
        return role

    def _parse_basic_auth(self, authorization: str) -> str | None:
        """Parse a Basic Auth header and extract the username.

        Expects the format ``"Basic <base64(username:password)>"``.
        The password is extracted but not verified (deferred to future
        password verification support).

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
            decoded = base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

        username, _, _ = decoded.partition(":")
        return username if username else None
