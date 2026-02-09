"""Tests for Policy Manifest models."""

import unittest

from adp_hypervisor.manifest.policy import (
    MandatoryFilterRule,
    OperationalRule,
    PolicyManifest,
    ResourcePolicy,
)
from adp_hypervisor.protocol.types import PredicateOperator

# =============================================================================
# MandatoryFilterRule Tests
# =============================================================================


class TestMandatoryFilterRule(unittest.TestCase):
    def test_string_value(self) -> None:
        rule = MandatoryFilterRule.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "fieldId": "closing_date",
                "op": "GT",
                "value": "2020-01-01",
            }
        )
        self.assertEqual(rule.field_id, "closing_date")
        self.assertEqual(rule.op, PredicateOperator.GT)
        self.assertEqual(rule.value, "2020-01-01")
        self.assertIsNone(rule.condition)

    def test_numeric_value(self) -> None:
        rule = MandatoryFilterRule(
            type="MANDATORY_FILTER", field_id="amount", op=PredicateOperator.GTE, value=100
        )
        self.assertEqual(rule.value, 100)

    def test_list_value(self) -> None:
        rule = MandatoryFilterRule.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "fieldId": "status",
                "op": "IN",
                "value": ["active", "pending"],
            }
        )
        self.assertEqual(rule.value, ["active", "pending"])

    def test_with_condition(self) -> None:
        rule = MandatoryFilterRule.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "fieldId": "date",
                "op": "GT",
                "value": "2020-01-01",
                "condition": "agent_tier == 'PRODUCTION'",
            }
        )
        self.assertEqual(rule.condition, "agent_tier == 'PRODUCTION'")


# =============================================================================
# OperationalRule Tests
# =============================================================================


class TestOperationalRule(unittest.TestCase):
    def test_enforce_limit(self) -> None:
        rule = OperationalRule.model_validate({"type": "OPERATIONAL", "enforceLimit": 100})
        self.assertEqual(rule.enforce_limit, 100)
        self.assertIsNone(rule.default_order_by)

    def test_default_order_by(self) -> None:
        rule = OperationalRule.model_validate(
            {
                "type": "OPERATIONAL",
                "defaultOrderBy": {"fieldId": "created_at", "direction": "DESC"},
            }
        )
        self.assertIsNotNone(rule.default_order_by)
        self.assertIsNotNone(rule.default_order_by)
        self.assertEqual(rule.default_order_by.field_id, "created_at")
        self.assertEqual(rule.default_order_by.direction, "DESC")

    def test_full_operational_rule(self) -> None:
        rule = OperationalRule.model_validate(
            {
                "type": "OPERATIONAL",
                "enforceLimit": 50,
                "defaultOrderBy": {"fieldId": "id", "direction": "ASC"},
                "condition": "agent_tier == 'BASIC'",
            }
        )
        self.assertEqual(rule.enforce_limit, 50)
        self.assertEqual(rule.condition, "agent_tier == 'BASIC'")


# =============================================================================
# ResourcePolicy Tests
# =============================================================================


class TestResourcePolicy(unittest.TestCase):
    def test_policy_with_rules(self) -> None:
        policy = ResourcePolicy.model_validate(
            {
                "resourceId": "com.acme:bank_failures",
                "rules": [
                    {
                        "type": "MANDATORY_FILTER",
                        "fieldId": "date",
                        "op": "GT",
                        "value": "2020-01-01",
                    },
                    {"type": "OPERATIONAL", "enforceLimit": 100},
                ],
            }
        )
        self.assertEqual(policy.resource_id, "com.acme:bank_failures")
        self.assertIsNotNone(policy.rules)
        self.assertIsNotNone(policy.rules)
        self.assertEqual(len(policy.rules), 2)
        self.assertIsInstance(policy.rules[0], MandatoryFilterRule)
        self.assertIsInstance(policy.rules[1], OperationalRule)

    def test_policy_no_rules(self) -> None:
        policy = ResourcePolicy.model_validate({"resourceId": "com.acme:test", "rules": []})
        self.assertEqual(policy.rules, [])

    def test_wildcard_resource_policy(self) -> None:
        policy = ResourcePolicy.model_validate(
            {
                "resourceId": "com.acme:*",
                "rules": [{"type": "OPERATIONAL", "enforceLimit": 50}],
            }
        )
        self.assertEqual(policy.resource_id, "com.acme:*")


# =============================================================================
# PolicyManifest Tests
# =============================================================================


class TestPolicyManifest(unittest.TestCase):
    def test_full_manifest(self) -> None:
        manifest = PolicyManifest.model_validate(
            {
                "version": "1.0.0",
                "policies": [
                    {
                        "resourceId": "com.acme:bank_failures",
                        "rules": [
                            {
                                "type": "MANDATORY_FILTER",
                                "fieldId": "date",
                                "op": "GT",
                                "value": "2020-01-01",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(manifest.version, "1.0.0")
        self.assertIsNotNone(manifest.policies)
        self.assertIsNotNone(manifest.policies)
        self.assertEqual(len(manifest.policies), 1)

    def test_bootstrap_no_policies(self) -> None:
        """Bootstrap mode: no policies."""
        manifest = PolicyManifest.model_validate({"version": "1.0.0"})
        self.assertIsNone(manifest.policies)

    def test_empty_policies(self) -> None:
        manifest = PolicyManifest.model_validate({"version": "1.0.0", "policies": []})
        self.assertEqual(manifest.policies, [])
