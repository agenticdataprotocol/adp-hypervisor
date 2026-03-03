"""
Describe Handler.

Implements the adp.describe method which returns the UsageContract
(field definitions and capabilities) for a specific resource and intent class.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import InvalidParamsError, ResourceNotFoundError
from adp_hypervisor.protocol.types import (
    Capabilities,
    DescribeRequestParams,
    DescribeResult,
    Field,
    FieldType,
    IntentClass,
    MutableCapability,
    PredicateCapability,
    PredicateOperator,
    PredicateUsage,
    ProjectionCapability,
    UsageContract,
)

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex

logger = logging.getLogger(__name__)

# Operator mapping by FieldType
# Operator Sets (Reusable groups of operators)
_BASIC_OPS = [
    PredicateOperator.EQ,
    PredicateOperator.NEQ,
]

_ORDERING_OPS = [
    PredicateOperator.GT,
    PredicateOperator.LT,
    PredicateOperator.GTE,
    PredicateOperator.LTE,
]

_MATCHING_OPS = [
    PredicateOperator.LIKE,
    PredicateOperator.ILIKE,
    PredicateOperator.CONTAINS,
]

_SET_OPS = [
    PredicateOperator.IN,
]

# Combined Operator Groups
_NUMERIC_OPS = _BASIC_OPS + _ORDERING_OPS + _SET_OPS
_TEXT_OPS = _NUMERIC_OPS + _MATCHING_OPS
_CONTAINER_OPS = _BASIC_OPS + [PredicateOperator.CONTAINS]
_VECTOR_OPS = [PredicateOperator.SIMILAR]


# Field Type Categories
_TEXT_TYPES = {
    FieldType.STRING,
    FieldType.DATE,
    FieldType.TIMESTAMP,
}

_NUMERIC_TYPES = {
    FieldType.INTEGER,
    FieldType.FLOAT,
}

_BASIC_TYPES = {
    FieldType.BOOLEAN,
}

_CONTAINER_TYPES = {
    FieldType.JSON,
    FieldType.BLOB,
}

_VECTOR_TYPES = {
    FieldType.VECTOR,
}


# Dynamic Operator Mapping Construction
_OPERATORS_BY_FIELD_TYPE: dict[FieldType, list[PredicateOperator]] = {}


def _register_operators(field_types: set[FieldType], operators: list[PredicateOperator]) -> None:
    for field_type in field_types:
        _OPERATORS_BY_FIELD_TYPE[field_type] = operators


_register_operators(_TEXT_TYPES, _TEXT_OPS)
_register_operators(_NUMERIC_TYPES, _NUMERIC_OPS)
_register_operators(_BASIC_TYPES, _BASIC_OPS)
_register_operators(_CONTAINER_TYPES, _CONTAINER_OPS)
_register_operators(_VECTOR_TYPES, _VECTOR_OPS)


def _get_operators_for_field(field_type: FieldType | None) -> list[PredicateOperator]:
    """Return allowed predicate operators for a given field type."""
    if field_type is None:
        return [PredicateOperator.EQ]
    return list(_OPERATORS_BY_FIELD_TYPE.get(field_type, [PredicateOperator.EQ]))


def _get_mandatory_field_ids(manifest_index: ManifestIndex, resource_id: str) -> set[str]:
    """Get field IDs that have MANDATORY_FILTER policy rules."""

    policies = manifest_index.get_mandatory_filter_policies(resource_id)
    return {p.field_id for p in policies}


def _build_read_capabilities(fields: list[Field], mandatory_field_ids: set[str]) -> Capabilities:
    """Build capabilities for READ intent classes (LOOKUP, QUERY)."""
    predicates = [
        PredicateCapability(
            field_id=f.field_id,
            usage=(
                PredicateUsage.REQUIRED
                if f.field_id in mandatory_field_ids
                else PredicateUsage.OPTIONAL
            ),
            operators=_get_operators_for_field(f.type),
        )
        for f in fields
    ]
    projections = [ProjectionCapability(field_id=f.field_id) for f in fields]
    return Capabilities(predicates=predicates, projections=projections)


def _build_write_capabilities(fields: list[Field]) -> Capabilities:
    """Build capabilities for WRITE intent classes (INGEST, REVISE)."""
    mutables = [MutableCapability(field_id=f.field_id) for f in fields]
    return Capabilities(mutables=mutables)


def _is_read_intent(intent_class: IntentClass) -> bool:
    return intent_class in (IntentClass.LOOKUP, IntentClass.QUERY)


class DescribeHandler(Handler):
    """Handler for the adp.describe method.

    Returns the UsageContract (field definitions and capabilities) for a
    specific resource and intent class. Capabilities are auto-derived from
    the resource's field types and policy rules.
    """

    def __init__(self, manifest_index: ManifestIndex, policy_enforcer: PolicyEnforcer) -> None:
        """Initialize the handler.

        Args:
            manifest_index: The manifest index to look up resources and policies.
            policy_enforcer: The policy enforcer to check access.
        """
        self._manifest_index = manifest_index
        self._policy_enforcer = policy_enforcer

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.describe"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process a describe request.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            A DescribeResult with the usage contract for the requested resource.

        Raises:
            InvalidParamsError: If the intent class is invalid or unsupported.
            ResourceNotFoundError: If the resource does not exist.
        """
        request = DescribeRequestParams.model_validate(params)

        role = self._policy_enforcer.resolve_role(params)

        self._validate_intent_class(request.intent_class)

        resource = self._manifest_index.get_resource(request.resource_id, version=request.version)
        if resource is None:
            raise ResourceNotFoundError(
                f"Resource not found: {request.resource_id!r}"
                + (f" version={request.version}" if request.version is not None else "")
            )

        self._validate_resource_supports_intent(
            request.resource_id, request.intent_class, resource.intent_classes
        )

        self._policy_enforcer.check_access(request.resource_id, role, request.intent_class)

        fields = self._extract_fields(resource)
        capabilities = self._build_capabilities(fields, request.intent_class, request.resource_id)

        logger.info(
            "Describe: resource=%s, version=%s, intent_class=%s, fields=%d",
            request.resource_id,
            resource.version,
            request.intent_class,
            len(fields),
        )

        return DescribeResult(
            resource_id=request.resource_id,
            version=resource.version or 1,
            intent_class=request.intent_class,
            usage_contract=UsageContract(fields=fields, capabilities=capabilities),
        )

    def _validate_intent_class(self, intent_class: IntentClass) -> None:
        if intent_class == IntentClass.WILDCARD:
            raise InvalidParamsError(
                "WILDCARD intent class is not allowed in describe requests. "
                "Please specify a concrete intent class (LOOKUP, QUERY, INGEST, REVISE)."
            )

    def _validate_resource_supports_intent(
        self,
        resource_id: str,
        intent_class: IntentClass,
        resource_intent_classes: list[IntentClass],
    ) -> None:
        if not resource_intent_classes:
            raise InvalidParamsError(
                f"Resource {resource_id!r} does not declare any supported intent classes. "
                "Use adp.discover to find resources supporting your intent class."
            )
        if (
            intent_class not in resource_intent_classes
            and IntentClass.WILDCARD not in resource_intent_classes
        ):
            supported = ", ".join(ic.value for ic in resource_intent_classes)
            raise InvalidParamsError(
                f"Resource {resource_id!r} does not support intent class {intent_class.value}. "
                f"Supported intent classes: {supported}. "
                "Use adp.discover to find resources supporting your intent class."
            )

    def _extract_fields(self, resource: Any) -> list[Field]:
        """Extract fields from the resource's source definition."""
        if resource.source_definition.fields:
            return list(resource.source_definition.fields)
        return []

    def _build_capabilities(
        self,
        fields: list[Field],
        intent_class: IntentClass,
        resource_id: str,
    ) -> Capabilities:
        if _is_read_intent(intent_class):
            # TODO: enforce policy rules once the policy spec is finalized.
            # Use _get_mandatory_field_ids(self._manifest_index, resource_id) to
            # derive REQUIRED predicates from MandatoryFilterRule entries.
            return _build_read_capabilities(fields, mandatory_field_ids=set())
        return _build_write_capabilities(fields)
