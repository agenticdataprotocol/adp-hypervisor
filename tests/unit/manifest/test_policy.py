"""Tests for Policy Manifest models."""

import unittest

from adp_hypervisor.manifest.policy import (
    AccessPolicy,
    MandatoryFilterPolicy,
    OperationalPolicy,
    PolicyManifest,
    RoleAccessEntry,
)
from adp_hypervisor.protocol.types import IntentClass, PredicateOperator

# =============================================================================
# MandatoryFilterPolicy Tests
# =============================================================================


class TestMandatoryFilterPolicy(unittest.TestCase):
    def test_string_value(self) -> None:
        policy = MandatoryFilterPolicy.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "resourceId": "com.acme.finance:bank_failures",
                "fieldId": "closing_date",
                "op": "GT",
                "value": "2020-01-01",
            }
        )
        self.assertEqual(policy.resource_id, "com.acme.finance:bank_failures")
        self.assertEqual(policy.field_id, "closing_date")
        self.assertEqual(policy.op, PredicateOperator.GT)
        self.assertEqual(policy.value, "2020-01-01")
        self.assertIsNone(policy.condition)

    def test_numeric_value(self) -> None:
        policy = MandatoryFilterPolicy(
            type="MANDATORY_FILTER",
            resource_id="com.acme:res",
            field_id="amount",
            op=PredicateOperator.GTE,
            value=100,
        )
        self.assertEqual(policy.value, 100)

    def test_list_value(self) -> None:
        policy = MandatoryFilterPolicy.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "resourceId": "com.acme:res",
                "fieldId": "status",
                "op": "IN",
                "value": ["active", "pending"],
            }
        )
        self.assertEqual(policy.value, ["active", "pending"])

    def test_with_condition(self) -> None:
        policy = MandatoryFilterPolicy.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "resourceId": "com.acme:res",
                "fieldId": "date",
                "op": "GT",
                "value": "2020-01-01",
                "condition": "agent_tier == 'PRODUCTION'",
            }
        )
        self.assertEqual(policy.condition, "agent_tier == 'PRODUCTION'")

    def test_resource_id_required(self) -> None:
        """resource_id is required; omitting it raises a validation error."""
        with self.assertRaises(ValueError):
            MandatoryFilterPolicy.model_validate(
                {"type": "MANDATORY_FILTER", "fieldId": "date", "op": "GT", "value": "2020-01-01"}
            )


# =============================================================================
# OperationalPolicy Tests
# =============================================================================


class TestOperationalPolicy(unittest.TestCase):
    def test_enforce_limit(self) -> None:
        policy = OperationalPolicy.model_validate(
            {"type": "OPERATIONAL", "resourceId": "com.acme:res", "enforceLimit": 100}
        )
        self.assertEqual(policy.resource_id, "com.acme:res")
        self.assertEqual(policy.enforce_limit, 100)
        self.assertIsNone(policy.default_order_by)

    def test_default_order_by(self) -> None:
        policy = OperationalPolicy.model_validate(
            {
                "type": "OPERATIONAL",
                "resourceId": "com.acme:res",
                "defaultOrderBy": {"fieldId": "created_at", "direction": "DESC"},
            }
        )
        self.assertIsNotNone(policy.default_order_by)
        self.assertEqual(policy.default_order_by.field_id, "created_at")
        self.assertEqual(policy.default_order_by.direction, "DESC")

    def test_full_operational_policy(self) -> None:
        policy = OperationalPolicy.model_validate(
            {
                "type": "OPERATIONAL",
                "resourceId": "com.acme:res",
                "enforceLimit": 50,
                "defaultOrderBy": {"fieldId": "id", "direction": "ASC"},
                "condition": "agent_tier == 'BASIC'",
            }
        )
        self.assertEqual(policy.enforce_limit, 50)
        self.assertEqual(policy.condition, "agent_tier == 'BASIC'")

    def test_resource_id_required(self) -> None:
        """resource_id is required; omitting it raises a validation error."""
        with self.assertRaises(ValueError):
            OperationalPolicy.model_validate({"type": "OPERATIONAL", "enforceLimit": 100})


# =============================================================================
# RoleAccessEntry Tests
# =============================================================================


class TestRoleAccessEntry(unittest.TestCase):
    def test_basic_entry(self) -> None:
        entry = RoleAccessEntry.model_validate(
            {"role": "admin", "allowedIntents": ["LOOKUP", "QUERY"]}
        )
        self.assertEqual(entry.role, "admin")
        self.assertIn(IntentClass.LOOKUP, entry.allowed_intents)
        self.assertIn(IntentClass.QUERY, entry.allowed_intents)

    def test_wildcard_intent(self) -> None:
        entry = RoleAccessEntry.model_validate({"role": "superuser", "allowedIntents": ["*"]})
        self.assertEqual(entry.allowed_intents[0], IntentClass.WILDCARD)

    def test_all_intents(self) -> None:
        entry = RoleAccessEntry.model_validate(
            {"role": "admin", "allowedIntents": ["LOOKUP", "QUERY", "INGEST", "REVISE"]}
        )
        self.assertEqual(len(entry.allowed_intents), 4)


# =============================================================================
# AccessPolicy Tests
# =============================================================================


class TestAccessPolicy(unittest.TestCase):
    def test_exact_resource_selector(self) -> None:
        policy = AccessPolicy.model_validate(
            {
                "type": "ACCESS",
                "resourceSelector": "com.acme.finance:bank_failures",
                "roles": [
                    {"role": "admin", "allowedIntents": ["LOOKUP", "QUERY", "REVISE", "INGEST"]},
                    {"role": "user", "allowedIntents": ["LOOKUP", "QUERY"]},
                ],
            }
        )
        self.assertEqual(policy.resource_selector, "com.acme.finance:bank_failures")
        self.assertEqual(len(policy.roles), 2)
        self.assertEqual(policy.roles[0].role, "admin")
        self.assertEqual(len(policy.roles[0].allowed_intents), 4)
        self.assertEqual(policy.roles[1].role, "user")

    def test_namespace_wildcard_selector(self) -> None:
        policy = AccessPolicy.model_validate(
            {
                "type": "ACCESS",
                "resourceSelector": "com.acme.finance:*",
                "roles": [{"role": "viewer", "allowedIntents": ["LOOKUP", "QUERY"]}],
            }
        )
        self.assertEqual(policy.resource_selector, "com.acme.finance:*")

    def test_global_wildcard_selector(self) -> None:
        policy = AccessPolicy.model_validate(
            {
                "type": "ACCESS",
                "resourceSelector": "*",
                "roles": [{"role": "default", "allowedIntents": ["*"]}],
            }
        )
        self.assertEqual(policy.resource_selector, "*")
        self.assertEqual(policy.roles[0].allowed_intents[0], IntentClass.WILDCARD)

    def test_namespace_prefix_selector(self) -> None:
        policy = AccessPolicy.model_validate(
            {
                "type": "ACCESS",
                "resourceSelector": "com.acme.*",
                "roles": [{"role": "superuser", "allowedIntents": ["*"]}],
            }
        )
        self.assertEqual(policy.resource_selector, "com.acme.*")

    def test_roles_required(self) -> None:
        """roles is required; omitting it raises a validation error."""
        with self.assertRaises(ValueError):
            AccessPolicy.model_validate({"type": "ACCESS", "resourceSelector": "com.acme:res"})


# =============================================================================
# PolicyManifest Tests
# =============================================================================


class TestPolicyManifest(unittest.TestCase):
    def test_full_manifest_flat_policies(self) -> None:
        manifest = PolicyManifest.model_validate(
            {
                "version": "1.0.0",
                "policies": [
                    {
                        "type": "ACCESS",
                        "resourceSelector": "com.acme:bank_failures",
                        "roles": [{"role": "admin", "allowedIntents": ["LOOKUP", "QUERY"]}],
                    },
                    {
                        "type": "MANDATORY_FILTER",
                        "resourceId": "com.acme:bank_failures",
                        "fieldId": "date",
                        "op": "GT",
                        "value": "2020-01-01",
                    },
                    {
                        "type": "OPERATIONAL",
                        "resourceId": "com.acme:bank_failures",
                        "enforceLimit": 100,
                    },
                ],
            }
        )
        self.assertEqual(manifest.version, "1.0.0")
        self.assertIsNotNone(manifest.policies)
        self.assertEqual(len(manifest.policies), 3)
        self.assertIsInstance(manifest.policies[0], AccessPolicy)
        self.assertIsInstance(manifest.policies[1], MandatoryFilterPolicy)
        self.assertIsInstance(manifest.policies[2], OperationalPolicy)

    def test_bootstrap_no_policies(self) -> None:
        """Bootstrap mode: no policies array."""
        manifest = PolicyManifest.model_validate({"version": "1.0.0"})
        self.assertIsNone(manifest.policies)

    def test_empty_policies(self) -> None:
        manifest = PolicyManifest.model_validate({"version": "1.0.0", "policies": []})
        self.assertEqual(manifest.policies, [])

    def test_mixed_policy_types_discriminated(self) -> None:
        """Policy discriminator correctly dispatches by 'type' field."""
        manifest = PolicyManifest.model_validate(
            {
                "version": "1.0.0",
                "policies": [
                    {
                        "type": "MANDATORY_FILTER",
                        "resourceId": "com.acme:r1",
                        "fieldId": "f",
                        "op": "EQ",
                        "value": "v",
                    },
                    {
                        "type": "OPERATIONAL",
                        "resourceId": "com.acme:r2",
                        "enforceLimit": 50,
                    },
                    {
                        "type": "ACCESS",
                        "resourceSelector": "com.acme:*",
                        "roles": [{"role": "user", "allowedIntents": ["QUERY"]}],
                    },
                ],
            }
        )
        types = [type(p).__name__ for p in manifest.policies]  # type: ignore[union-attr]
        self.assertEqual(types, ["MandatoryFilterPolicy", "OperationalPolicy", "AccessPolicy"])
