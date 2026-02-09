"""
Policy Manifest models.

Defines the types for the ADP Curation Plane's policy layer,
which specifies governance rules and constraints for resource access.
Based on the PolicyManifest section of curation.ts.
"""

from typing import Annotated, Literal

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import (
    ADPModel,
    PredicateOperator,
    ResourceId,
    SortOrder,
)

PolicyCondition = str
"""Condition expression for conditional policy rules."""


class MandatoryFilterRule(ADPModel):
    """Mandatory filter rule that enforces required predicates."""

    type: Literal["MANDATORY_FILTER"] = PydanticField(..., description="Type of policy rule")
    field_id: str = PydanticField(..., description="Field identifier for the mandatory filter")
    op: PredicateOperator = PydanticField(..., description="Operator for the mandatory filter")
    value: str | int | float | bool | list[str | int | float | bool] = PydanticField(
        ..., description="Value for the mandatory filter"
    )
    condition: PolicyCondition | None = PydanticField(
        default=None, description="Optional condition for when this rule applies"
    )


class OperationalRule(ADPModel):
    """Operational constraints for resource access."""

    type: Literal["OPERATIONAL"] = PydanticField(..., description="Type of policy rule")
    enforce_limit: int | None = PydanticField(
        default=None, description="Maximum number of results to return"
    )
    default_order_by: SortOrder | None = PydanticField(
        default=None, description="Default sort order to apply"
    )
    condition: PolicyCondition | None = PydanticField(
        default=None, description="Optional condition for when this rule applies"
    )


PolicyRule = Annotated[
    MandatoryFilterRule | OperationalRule,
    PydanticField(discriminator="type"),
]
"""Union type for all policy rule types."""


class ResourcePolicy(ADPModel):
    """Policy rules for a specific resource."""

    resource_id: ResourceId = PydanticField(
        ..., description="Resource identifier for which these policies apply"
    )
    rules: list[PolicyRule] | None = PydanticField(
        default=None, description="List of policy rules to apply"
    )


class PolicyManifest(ADPModel):
    """Root structure for the policy manifest (policy.yaml)."""

    version: str = PydanticField(..., description="Version of the manifest schema")
    policies: list[ResourcePolicy] | None = PydanticField(
        default=None,
        description="List of resource policies. If omitted, no enforcements are applied",
    )
