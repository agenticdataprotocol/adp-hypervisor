"""Tests for PolicyEnforcer."""

import unittest
from unittest.mock import MagicMock

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.policy import AccessPolicy, RoleAccessEntry
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.policy.authenticator import Authenticator
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.policy.role_resolver import RoleResolver
from adp_hypervisor.protocol.errors import UnauthorizedError
from adp_hypervisor.protocol.types import IntentClass


def _make_access_policy(
    resource_selector: str,
    roles: list[RoleAccessEntry],
) -> AccessPolicy:
    """Create an AccessPolicy test instance."""
    return AccessPolicy(
        type="ACCESS",
        resource_selector=resource_selector,
        roles=roles,
    )


def _make_role_entry(role: str, allowed_intents: list[IntentClass]) -> RoleAccessEntry:
    """Create a RoleAccessEntry test instance."""
    return RoleAccessEntry(role=role, allowed_intents=allowed_intents)


def _make_resource(resource_id: str) -> CuratedResource:
    """Create a minimal CuratedResource for filtering tests."""
    return CuratedResource(
        resource_id=resource_id,
        version=1,
        intent_classes=[IntentClass.QUERY],
        backend_id="test_backend",
        source_definition=SourceDefinition(source="test_table"),
    )


def _make_enforcer(
    manifest_index: ManifestIndex | None = None,
    authenticator: Authenticator | None = None,
    role_resolver: RoleResolver | None = None,
) -> PolicyEnforcer:
    """Create a PolicyEnforcer with mocked dependencies."""
    if manifest_index is None:
        manifest_index = MagicMock(spec=ManifestIndex)
    if authenticator is None:
        authenticator = MagicMock(spec=Authenticator)
    if role_resolver is None:
        role_resolver = MagicMock(spec=RoleResolver)
    return PolicyEnforcer(
        manifest_index=manifest_index,
        authenticator=authenticator,
        role_resolver=role_resolver,
    )


# =============================================================================
# TestCheckAccess
# =============================================================================


class TestCheckAccess(unittest.TestCase):
    """Tests for PolicyEnforcer.check_access."""

    def test_access_allowed(self) -> None:
        """Policy matches with role allowed for intent — no exception."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("ns:res", [_make_role_entry("admin", [IntentClass.QUERY])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        enforcer.check_access("ns:res", "admin", IntentClass.QUERY)

    def test_access_denied_wrong_intent(self) -> None:
        """Role is present but intent not in allowedIntents — UnauthorizedError."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("ns:res", [_make_role_entry("admin", [IntentClass.QUERY])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        with self.assertRaises(UnauthorizedError):
            enforcer.check_access("ns:res", "admin", IntentClass.INGEST)

    def test_access_denied_wrong_role(self) -> None:
        """Role not in any policy roles — UnauthorizedError."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("ns:res", [_make_role_entry("admin", [IntentClass.QUERY])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        with self.assertRaises(UnauthorizedError):
            enforcer.check_access("ns:res", "viewer", IntentClass.QUERY)

    def test_no_policy_matches(self) -> None:
        """get_access_policies returns empty list — UnauthorizedError (closed-by-default)."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = []
        enforcer = _make_enforcer(manifest_index=index)

        with self.assertRaises(UnauthorizedError):
            enforcer.check_access("ns:res", "admin", IntentClass.QUERY)

    def test_wildcard_intent(self) -> None:
        """allowedIntents contains IntentClass.WILDCARD — all intents allowed."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("ns:res", [_make_role_entry("admin", [IntentClass.WILDCARD])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        enforcer.check_access("ns:res", "admin", IntentClass.QUERY)
        enforcer.check_access("ns:res", "admin", IntentClass.LOOKUP)
        enforcer.check_access("ns:res", "admin", IntentClass.INGEST)
        enforcer.check_access("ns:res", "admin", IntentClass.REVISE)

    def test_multiple_policies_merge(self) -> None:
        """Two policies, same role in both — union of allowedIntents."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("ns:res", [_make_role_entry("analyst", [IntentClass.QUERY])]),
            _make_access_policy("ns:res", [_make_role_entry("analyst", [IntentClass.LOOKUP])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        enforcer.check_access("ns:res", "analyst", IntentClass.QUERY)
        enforcer.check_access("ns:res", "analyst", IntentClass.LOOKUP)

        with self.assertRaises(UnauthorizedError):
            enforcer.check_access("ns:res", "analyst", IntentClass.INGEST)

    def test_multiple_roles_in_policy(self) -> None:
        """Policy has multiple roles — only matching role's intents checked."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy(
                "ns:res",
                [
                    _make_role_entry("admin", [IntentClass.WILDCARD]),
                    _make_role_entry("viewer", [IntentClass.LOOKUP]),
                ],
            ),
        ]
        enforcer = _make_enforcer(manifest_index=index)

        enforcer.check_access("ns:res", "admin", IntentClass.INGEST)
        enforcer.check_access("ns:res", "viewer", IntentClass.LOOKUP)

        with self.assertRaises(UnauthorizedError):
            enforcer.check_access("ns:res", "viewer", IntentClass.INGEST)


# =============================================================================
# TestFilterAccessibleResources
# =============================================================================


class TestFilterAccessibleResources(unittest.TestCase):
    """Tests for PolicyEnforcer.filter_accessible_resources."""

    def test_all_accessible(self) -> None:
        """All resources have matching policies — all returned."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = [
            _make_access_policy("*", [_make_role_entry("user", [IntentClass.QUERY])]),
        ]
        enforcer = _make_enforcer(manifest_index=index)
        resources = [_make_resource("ns:a"), _make_resource("ns:b")]

        result = enforcer.filter_accessible_resources(resources, "user")

        self.assertEqual(len(result), 2)
        self.assertEqual([r.resource_id for r in result], ["ns:a", "ns:b"])

    def test_none_accessible(self) -> None:
        """No resources have matching policies — empty list."""
        index = MagicMock(spec=ManifestIndex)
        index.get_access_policies_for_resource.return_value = []
        enforcer = _make_enforcer(manifest_index=index)
        resources = [_make_resource("ns:a"), _make_resource("ns:b")]

        result = enforcer.filter_accessible_resources(resources, "user")

        self.assertEqual(result, [])

    def test_mixed_access(self) -> None:
        """Some accessible, some not — only accessible returned."""
        index = MagicMock(spec=ManifestIndex)
        policy = _make_access_policy("ns:a", [_make_role_entry("user", [IntentClass.QUERY])])

        def side_effect(resource_id: str) -> list[AccessPolicy]:
            if resource_id == "ns:a":
                return [policy]
            return []

        index.get_access_policies_for_resource.side_effect = side_effect
        enforcer = _make_enforcer(manifest_index=index)
        resources = [_make_resource("ns:a"), _make_resource("ns:b")]

        result = enforcer.filter_accessible_resources(resources, "user")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].resource_id, "ns:a")

    def test_empty_resource_list(self) -> None:
        """Empty input — empty output."""
        enforcer = _make_enforcer()

        result = enforcer.filter_accessible_resources([], "user")

        self.assertEqual(result, [])


# =============================================================================
# TestResolveRole
# =============================================================================


class TestResolveRole(unittest.TestCase):
    """Tests for PolicyEnforcer.resolve_role."""

    def test_delegates_to_authenticator_and_role_resolver(self) -> None:
        """Verify resolve_role authenticates then resolves role."""
        authenticator = MagicMock(spec=Authenticator)
        authenticator.authenticate.return_value = "alice"
        resolver = MagicMock(spec=RoleResolver)
        resolver.resolve.return_value = "analyst"
        enforcer = _make_enforcer(authenticator=authenticator, role_resolver=resolver)
        params = {"_meta": {"authorization": "Basic dXNlcjpwYXNz"}}

        role = enforcer.resolve_role(params)

        self.assertEqual(role, "analyst")
        authenticator.authenticate.assert_called_once_with(params)
        resolver.resolve.assert_called_once_with("alice")


if __name__ == "__main__":
    unittest.main()
