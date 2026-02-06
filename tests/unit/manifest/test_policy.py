"""Tests for Policy Manifest models."""

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


class TestMandatoryFilterRule:
    def test_string_value(self) -> None:
        rule = MandatoryFilterRule.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "fieldId": "closing_date",
                "op": "GT",
                "value": "2020-01-01",
            }
        )
        assert rule.field_id == "closing_date"
        assert rule.op == PredicateOperator.GT
        assert rule.value == "2020-01-01"
        assert rule.condition is None

    def test_numeric_value(self) -> None:
        rule = MandatoryFilterRule(field_id="amount", op=PredicateOperator.GTE, value=100)
        assert rule.value == 100

    def test_list_value(self) -> None:
        rule = MandatoryFilterRule.model_validate(
            {
                "type": "MANDATORY_FILTER",
                "fieldId": "status",
                "op": "IN",
                "value": ["active", "pending"],
            }
        )
        assert rule.value == ["active", "pending"]

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
        assert rule.condition == "agent_tier == 'PRODUCTION'"


# =============================================================================
# OperationalRule Tests
# =============================================================================


class TestOperationalRule:
    def test_enforce_limit(self) -> None:
        rule = OperationalRule.model_validate({"type": "OPERATIONAL", "enforceLimit": 100})
        assert rule.enforce_limit == 100
        assert rule.default_order_by is None

    def test_default_order_by(self) -> None:
        rule = OperationalRule.model_validate(
            {
                "type": "OPERATIONAL",
                "defaultOrderBy": {"fieldId": "created_at", "direction": "DESC"},
            }
        )
        assert rule.default_order_by is not None
        assert rule.default_order_by.field_id == "created_at"
        assert rule.default_order_by.direction == "DESC"

    def test_full_operational_rule(self) -> None:
        rule = OperationalRule.model_validate(
            {
                "type": "OPERATIONAL",
                "enforceLimit": 50,
                "defaultOrderBy": {"fieldId": "id", "direction": "ASC"},
                "condition": "agent_tier == 'BASIC'",
            }
        )
        assert rule.enforce_limit == 50
        assert rule.condition == "agent_tier == 'BASIC'"


# =============================================================================
# ResourcePolicy Tests
# =============================================================================


class TestResourcePolicy:
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
        assert policy.resource_id == "com.acme:bank_failures"
        assert policy.rules is not None
        assert len(policy.rules) == 2
        assert isinstance(policy.rules[0], MandatoryFilterRule)
        assert isinstance(policy.rules[1], OperationalRule)

    def test_policy_no_rules(self) -> None:
        policy = ResourcePolicy.model_validate({"resourceId": "com.acme:test", "rules": []})
        assert policy.rules == []

    def test_wildcard_resource_policy(self) -> None:
        policy = ResourcePolicy.model_validate(
            {
                "resourceId": "com.acme:*",
                "rules": [{"type": "OPERATIONAL", "enforceLimit": 50}],
            }
        )
        assert policy.resource_id == "com.acme:*"


# =============================================================================
# PolicyManifest Tests
# =============================================================================


class TestPolicyManifest:
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
        assert manifest.version == "1.0.0"
        assert manifest.policies is not None
        assert len(manifest.policies) == 1

    def test_bootstrap_no_policies(self) -> None:
        """Bootstrap mode: no policies."""
        manifest = PolicyManifest.model_validate({"version": "1.0.0"})
        assert manifest.policies is None

    def test_empty_policies(self) -> None:
        manifest = PolicyManifest.model_validate({"version": "1.0.0", "policies": []})
        assert manifest.policies == []
