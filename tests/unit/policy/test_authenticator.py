"""Tests for Authenticator."""

import base64
import unittest

import adp_hypervisor.protocol.types  # noqa: F401 — pre-load to avoid circular import
from adp_hypervisor.policy.authenticator import Authenticator
from adp_hypervisor.policy.basic_authenticator import BasicAuthenticator
from adp_hypervisor.protocol.errors import UnauthorizedError

# =============================================================================
# Helpers
# =============================================================================


def _basic_auth(username: str, password: str = "") -> str:
    """Build a Basic Auth header value."""
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def _params_with_auth(authorization: str) -> dict[str, object]:
    """Build JSON-RPC params with an authorization header in _meta."""
    return {"_meta": {"authorization": authorization}}


# =============================================================================
# TestAuthenticatorABC
# =============================================================================


class TestAuthenticatorABC(unittest.TestCase):
    """Tests for the Authenticator abstract base class."""

    def test_authenticator_is_abstract(self) -> None:
        """Authenticator cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            Authenticator()  # type: ignore[abstract]


# =============================================================================
# TestBasicAuthenticator
# =============================================================================


class TestBasicAuthenticator(unittest.TestCase):
    """Tests for BasicAuthenticator.authenticate() covering Basic Auth parsing."""

    def setUp(self) -> None:
        self.authenticator = BasicAuthenticator()

    # -- Basic Auth parsing ---------------------------------------------------

    def test_valid_basic_auth(self) -> None:
        """Valid Basic Auth extracts the username."""
        params = _params_with_auth(_basic_auth("alice", "pass"))
        self.assertEqual(self.authenticator.authenticate(params), "alice")

    def test_no_meta(self) -> None:
        """Params with no _meta key raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate({})

    def test_empty_meta(self) -> None:
        """Empty _meta dict raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate({"_meta": {}})

    def test_no_authorization(self) -> None:
        """_meta without authorization key raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate({"_meta": {"other": "val"}})

    def test_empty_authorization(self) -> None:
        """Empty authorization string raises UnauthorizedError."""
        params = _params_with_auth("")
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate(params)

    def test_non_string_authorization(self) -> None:
        """Non-string authorization value raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate({"_meta": {"authorization": 123}})

    def test_non_dict_meta(self) -> None:
        """Non-dict _meta value raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate({"_meta": "not a dict"})

    def test_invalid_scheme(self) -> None:
        """Non-Basic scheme raises UnauthorizedError."""
        params = _params_with_auth("Bearer token123")
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate(params)

    def test_invalid_base64(self) -> None:
        """Invalid base64 payload raises UnauthorizedError."""
        params = _params_with_auth("Basic !!!invalid!!!")
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate(params)

    def test_no_colon_in_decoded(self) -> None:
        """Base64 without colon treats entire string as username."""
        encoded = base64.b64encode(b"useronly").decode()
        params = _params_with_auth(f"Basic {encoded}")
        self.assertEqual(self.authenticator.authenticate(params), "useronly")

    def test_empty_username(self) -> None:
        """Empty username (colon-prefixed) raises UnauthorizedError."""
        encoded = base64.b64encode(b":password").decode()
        params = _params_with_auth(f"Basic {encoded}")
        with self.assertRaises(UnauthorizedError):
            self.authenticator.authenticate(params)

    def test_password_not_required(self) -> None:
        """Username without password is valid."""
        params = _params_with_auth(_basic_auth("alice"))
        self.assertEqual(self.authenticator.authenticate(params), "alice")


if __name__ == "__main__":
    unittest.main()
