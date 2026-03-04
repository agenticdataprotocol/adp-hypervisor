"""Tests for RoleResolver."""

import unittest

import adp_hypervisor.protocol.types  # noqa: F401 — pre-load to avoid circular import
from adp_hypervisor.policy.role_resolver import RoleResolver, UserRoleConfig
from adp_hypervisor.policy.yaml_role_resolver import YamlRoleResolver

# =============================================================================
# Helpers
# =============================================================================


def _make_resolver(
    users: dict[str, str] | None = None,
    default_role: str = "default",
) -> tuple[UserRoleConfig, YamlRoleResolver]:
    """Create a YamlRoleResolver with the given config."""
    config = UserRoleConfig(default_role=default_role, users=users or {})
    return config, YamlRoleResolver(config)


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
# TestYamlRoleResolver
# =============================================================================


class TestYamlRoleResolver(unittest.TestCase):
    """Tests for YamlRoleResolver.resolve() covering role lookup."""

    def setUp(self) -> None:
        self.config, self.resolver = _make_resolver(
            users={"alice": "analyst", "bob": "admin"},
        )

    def test_known_user(self) -> None:
        """Known user resolves to the configured role."""
        self.assertEqual(self.resolver.resolve("alice"), "analyst")

    def test_unknown_user(self) -> None:
        """Unknown user falls back to default role."""
        self.assertEqual(self.resolver.resolve("unknown"), "default")

    def test_custom_default_role(self) -> None:
        """Config with custom default_role returns that role for unknown users."""
        _, resolver = _make_resolver(default_role="guest")
        self.assertEqual(resolver.resolve("nobody"), "guest")

    def test_default_role_property(self) -> None:
        """default_role property exposes the configured default."""
        self.assertEqual(self.resolver.default_role, "default")


if __name__ == "__main__":
    unittest.main()
