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
