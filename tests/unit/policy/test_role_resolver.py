"""Tests for RoleResolver."""

import base64
import unittest

import adp_hypervisor.protocol.types  # noqa: F401 — pre-load to avoid circular import
from adp_hypervisor.policy.role_resolver import RoleResolver, SimpleAuthResolver, UserRoleConfig
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


def _make_resolver(
    users: dict[str, str] | None = None,
    default_role: str = "default",
) -> tuple[UserRoleConfig, SimpleAuthResolver]:
    """Create a SimpleAuthResolver with the given config."""
    config = UserRoleConfig(default_role=default_role, users=users or {})
    return config, SimpleAuthResolver(config)


# =============================================================================
# TestUserRoleConfig
# =============================================================================


class TestUserRoleConfig(unittest.TestCase):
    """Tests for UserRoleConfig model defaults and construction."""

    def test_defaults(self) -> None:
        """Empty config has default_role='default' and empty users."""
        config = UserRoleConfig()
        self.assertEqual(config.default_role, "default")
        self.assertEqual(config.users, {})

    def test_custom_config(self) -> None:
        """Config with custom default_role and users."""
        config = UserRoleConfig(
            default_role="guest",
            users={"alice": "analyst", "bob": "admin"},
        )
        self.assertEqual(config.default_role, "guest")
        self.assertEqual(config.users, {"alice": "analyst", "bob": "admin"})

    def test_from_dict(self) -> None:
        """model_validate from a dict (simulating YAML load)."""
        data = {"default_role": "viewer", "users": {"carol": "editor"}}
        config = UserRoleConfig.model_validate(data)
        self.assertEqual(config.default_role, "viewer")
        self.assertEqual(config.users, {"carol": "editor"})


# =============================================================================
# TestRoleResolverABC
# =============================================================================


class TestRoleResolverABC(unittest.TestCase):
    """Tests for the RoleResolver abstract base class."""

    def test_role_resolver_is_abstract(self) -> None:
        """RoleResolver cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            RoleResolver()  # type: ignore[abstract]


# =============================================================================
# TestSimpleAuthResolver
# =============================================================================


class TestSimpleAuthResolver(unittest.TestCase):
    """Tests for SimpleAuthResolver.resolve() covering auth parsing and role lookup."""

    def setUp(self) -> None:
        self.config, self.resolver = _make_resolver(
            users={"alice": "analyst", "bob": "admin"},
        )

    # -- Simple Auth parsing --------------------------------------------------

    def test_valid_basic_auth(self) -> None:
        """Valid Simple Auth resolves to the mapped role."""
        params = _params_with_auth(_basic_auth("alice", "pass"))
        self.assertEqual(self.resolver.resolve(params), "analyst")

    def test_no_meta(self) -> None:
        """Params with no _meta key raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve({})

    def test_empty_meta(self) -> None:
        """Empty _meta dict raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve({"_meta": {}})

    def test_no_authorization(self) -> None:
        """_meta without authorization key raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve({"_meta": {"other": "val"}})

    def test_empty_authorization(self) -> None:
        """Empty authorization string raises UnauthorizedError."""
        params = _params_with_auth("")
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve(params)

    def test_non_string_authorization(self) -> None:
        """Non-string authorization value raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve({"_meta": {"authorization": 123}})

    def test_non_dict_meta(self) -> None:
        """Non-dict _meta value raises UnauthorizedError."""
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve({"_meta": "not a dict"})

    def test_invalid_scheme(self) -> None:
        """Non-Basic scheme raises UnauthorizedError."""
        params = _params_with_auth("Bearer token123")
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve(params)

    def test_invalid_base64(self) -> None:
        """Invalid base64 payload raises UnauthorizedError."""
        params = _params_with_auth("Basic !!!invalid!!!")
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve(params)

    def test_no_colon_in_decoded(self) -> None:
        """Base64 without colon treats entire string as username."""
        encoded = base64.b64encode(b"useronly").decode()
        params = _params_with_auth(f"Basic {encoded}")
        # "useronly" is not in users, so falls back to default role
        self.assertEqual(self.resolver.resolve(params), "default")

    def test_empty_username(self) -> None:
        """Empty username (colon-prefixed) raises UnauthorizedError."""
        encoded = base64.b64encode(b":password").decode()
        params = _params_with_auth(f"Basic {encoded}")
        with self.assertRaises(UnauthorizedError):
            self.resolver.resolve(params)

    # -- Role lookup ----------------------------------------------------------

    def test_known_user(self) -> None:
        """Known user resolves to the configured role."""
        params = _params_with_auth(_basic_auth("alice", "secret"))
        self.assertEqual(self.resolver.resolve(params), "analyst")

    def test_unknown_user(self) -> None:
        """Unknown user falls back to default role."""
        params = _params_with_auth(_basic_auth("unknown", "pass"))
        self.assertEqual(self.resolver.resolve(params), "default")

    def test_custom_default_role(self) -> None:
        """Config with custom default_role returns that role for unknown users."""
        _, resolver = _make_resolver(default_role="guest")
        params = _params_with_auth(_basic_auth("nobody", "pass"))
        self.assertEqual(resolver.resolve(params), "guest")

    def test_default_role_property(self) -> None:
        """default_role property exposes the configured default."""
        self.assertEqual(self.resolver.default_role, "default")


if __name__ == "__main__":
    unittest.main()
