"""
Role Resolver.

Defines the role resolution interface (ABC) and the user-role config model.
"""

import abc
from typing import Any

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import ADPModel


class UserRoleConfig(ADPModel):
    """Configuration for user-to-role mapping.

    Loaded from ``users.yaml`` at server startup. Maps usernames to roles
    and provides a default role for unknown users who provide valid credentials.
    """

    default_role: str = PydanticField(
        default="default",
        description="Role assigned to unknown users who provide valid credentials",
    )
    users: dict[str, str] = PydanticField(
        default_factory=dict,
        description="Mapping of username to role (e.g. {'admin': 'admin', 'alice': 'analyst'})",
    )


class RoleResolver(abc.ABC):
    """Abstract interface for resolving user identity to a role.

    Implementations extract user identity from JSON-RPC request params
    and map it to a role string used by ACCESS policy enforcement.

    Subclass this to integrate with different auth backends
    (e.g. Gravitino, OAuth, LDAP).
    """

    @abc.abstractmethod
    def resolve(self, params: dict[str, Any]) -> str:
        """Resolve user identity from request params to a role.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The resolved role string.

        Raises:
            UnauthorizedError: If credentials are missing or malformed.
        """
