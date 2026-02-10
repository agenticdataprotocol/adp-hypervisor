"""
Validate Handler.

Implements the adp.validate method which validates an Intent IR
against a resource's schema and policy rules before execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.manifest.policy import MandatoryFilterRule, OperationalRule
from adp_hypervisor.protocol.errors import ResourceNotFoundError
from adp_hypervisor.protocol.types import (
    Field,
    FieldType,
    IngestIntent,
    IssueSeverity,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
    ValidateRequestParams,
    ValidateResult,
    ValidationIssue,
    ValidationIssueCode,
)

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex
    from adp_hypervisor.manifest.semantic import CuratedResource

logger = logging.getLogger(__name__)


# =============================================================================
# Operator mapping by FieldType
# =============================================================================

_BASIC_OPS = [PredicateOperator.EQ, PredicateOperator.NEQ]

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

_SET_OPS = [PredicateOperator.IN]

_NUMERIC_OPS = _BASIC_OPS + _ORDERING_OPS + _SET_OPS
_TEXT_OPS = _NUMERIC_OPS + _MATCHING_OPS
_CONTAINER_OPS = _BASIC_OPS + [PredicateOperator.CONTAINS]
_VECTOR_OPS = [PredicateOperator.SIMILAR]

_OPERATORS_BY_FIELD_TYPE: dict[FieldType, list[PredicateOperator]] = {}


def _register_operators(field_types: set[FieldType], operators: list[PredicateOperator]) -> None:
    for ft in field_types:
        _OPERATORS_BY_FIELD_TYPE[ft] = operators


_register_operators({FieldType.STRING, FieldType.DATE, FieldType.TIMESTAMP}, _TEXT_OPS)
_register_operators({FieldType.INTEGER, FieldType.FLOAT}, _NUMERIC_OPS)
_register_operators({FieldType.BOOLEAN}, _BASIC_OPS)
_register_operators({FieldType.JSON, FieldType.BLOB}, _CONTAINER_OPS)
_register_operators({FieldType.VECTOR}, _VECTOR_OPS)


def _get_operators_for_field(field_type: FieldType) -> list[PredicateOperator]:
    """Return allowed predicate operators for a given field type."""
    return list(_OPERATORS_BY_FIELD_TYPE.get(field_type, [PredicateOperator.EQ]))


# =============================================================================
# Predicate extraction
# =============================================================================


def _collect_predicates(group: PredicateGroup) -> list[Predicate]:
    """Recursively collect all leaf Predicate instances from a PredicateGroup."""
    result: list[Predicate] = []
    for item in group.predicates:
        if isinstance(item, PredicateGroup):
            result.extend(_collect_predicates(item))
        else:
            result.append(item)
    return result


# =============================================================================
# ValidateHandler
# =============================================================================


class ValidateHandler(Handler):
    """Handler for the adp.validate method.

    Validates an Intent IR against a resource's field schema and policy
    rules. Returns a list of validation issues (if any) with severity
    levels indicating whether execution should proceed.
    """

    def __init__(self, manifest_index: ManifestIndex) -> None:
        """Initialize the handler.

        Args:
            manifest_index: The manifest index to look up resources and policies.
        """
        self._manifest_index = manifest_index

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.validate"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process a validate request.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            A ValidateResult indicating whether the intent is valid.

        Raises:
            ResourceNotFoundError: If the resource does not exist.
        """
        request = ValidateRequestParams.model_validate(params)

        resource = self._manifest_index.get_resource(request.resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource not found: {request.resource_id!r}")

        fields = self._extract_fields(resource)
        field_map = {f.field_id: f for f in fields}

        issues: list[ValidationIssue] = []
        intent = request.intent

        if isinstance(intent, LookupIntent):
            self._validate_lookup(intent, field_map, issues)
        elif isinstance(intent, QueryIntent):
            self._validate_query(intent, field_map, issues)
        elif isinstance(intent, IngestIntent):
            self._validate_ingest(intent, field_map, issues)
        elif isinstance(intent, ReviseIntent):
            self._validate_revise(intent, field_map, issues)

        self._apply_policy_rules(request.resource_id, intent, issues)

        has_blocking = any(i.severity == IssueSeverity.BLOCKING for i in issues)

        logger.info(
            "Validate: resource=%s, intent_class=%s, valid=%s, issues=%d",
            request.resource_id,
            intent.intent_class,
            not has_blocking,
            len(issues),
        )

        return ValidateResult(
            valid=not has_blocking,
            issues=issues if issues else None,
        )

    # ------------------------------------------------------------------
    # Intent-specific validation
    # ------------------------------------------------------------------

    def _extract_fields(self, resource: CuratedResource) -> list[Field]:
        """Extract fields from the resource's first source definition."""
        if resource.sources and resource.sources[0].fields:
            return list(resource.sources[0].fields)
        return []

    def _validate_lookup(
        self,
        intent: LookupIntent,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Validate a LOOKUP intent."""
        self._check_field_exists(intent.key.field_id, field_map, issues)

        if intent.projections:
            self._check_projections(intent.projections, field_map, issues)

    def _validate_query(
        self,
        intent: QueryIntent,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Validate a QUERY intent."""
        predicates = _collect_predicates(intent.predicates)
        for pred in predicates:
            self._check_field_exists(pred.field_id, field_map, issues)
            if pred.field_id in field_map:
                self._check_operator(pred.field_id, pred.op, field_map, issues)

        if intent.projections:
            self._check_projections(intent.projections, field_map, issues)

        if intent.order_by:
            for sort in intent.order_by:
                self._check_field_exists(sort.field_id, field_map, issues)

    def _validate_ingest(
        self,
        intent: IngestIntent,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Validate an INGEST intent."""
        seen: set[str] = set()
        for record in intent.payload:
            for key in record:
                if key not in seen:
                    self._check_field_exists(key, field_map, issues)
                    seen.add(key)

    def _validate_revise(
        self,
        intent: ReviseIntent,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Validate a REVISE intent."""
        predicates = _collect_predicates(intent.predicates)
        for pred in predicates:
            self._check_field_exists(pred.field_id, field_map, issues)
            if pred.field_id in field_map:
                self._check_operator(pred.field_id, pred.op, field_map, issues)

        for key in intent.payload:
            self._check_field_exists(key, field_map, issues)

    # ------------------------------------------------------------------
    # Shared validation helpers
    # ------------------------------------------------------------------

    def _check_field_exists(
        self,
        field_id: str,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Check that a field exists in the resource schema."""
        if field_id not in field_map:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.FIELD_NOT_FOUND,
                    field=field_id,
                    severity=IssueSeverity.BLOCKING,
                    message=f"Field {field_id!r} does not exist in resource schema",
                    correction_hint=(
                        "Check the field name against the resource's DESCRIBE response."
                    ),
                )
            )

    def _check_operator(
        self,
        field_id: str,
        op: PredicateOperator,
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Check that an operator is valid for a field's type."""
        field = field_map[field_id]
        allowed = _get_operators_for_field(field.type)
        if op not in allowed:
            allowed_str = ", ".join(str(o) for o in allowed)
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.INVALID_OPERATOR,
                    field=field_id,
                    severity=IssueSeverity.BLOCKING,
                    message=(
                        f"Operator {op!r} is not valid for field {field_id!r} "
                        f"of type {field.type!r}"
                    ),
                    correction_hint=f"Allowed operators: {allowed_str}.",
                )
            )

    def _check_projections(
        self,
        projections: list[str],
        field_map: dict[str, Field],
        issues: list[ValidationIssue],
    ) -> None:
        """Check that all projection fields exist in the resource schema."""
        for field_id in projections:
            self._check_field_exists(field_id, field_map, issues)

    # ------------------------------------------------------------------
    # Policy rule validation
    # ------------------------------------------------------------------

    def _apply_policy_rules(
        self,
        resource_id: str,
        intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent,
        issues: list[ValidationIssue],
    ) -> None:
        """Apply policy rules to the intent."""
        policy = self._manifest_index.get_policy(resource_id)
        if policy is None or policy.rules is None:
            return

        for rule in policy.rules:
            if isinstance(rule, MandatoryFilterRule):
                self._check_mandatory_filter(rule, intent, issues)
            elif isinstance(rule, OperationalRule):
                self._check_operational_rule(rule, intent, issues)

    def _check_mandatory_filter(
        self,
        rule: MandatoryFilterRule,
        intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent,
        issues: list[ValidationIssue],
    ) -> None:
        """Check that a mandatory filter predicate is present in the intent."""
        if isinstance(intent, IngestIntent):
            return

        if isinstance(intent, LookupIntent):
            if (
                intent.key.field_id == rule.field_id
                and intent.key.op == rule.op
                and intent.key.value == rule.value
            ):
                return
        else:
            predicates = _collect_predicates(intent.predicates)
            for pred in predicates:
                if (
                    pred.field_id == rule.field_id
                    and pred.op == rule.op
                    and pred.value == rule.value
                ):
                    return

        issues.append(
            ValidationIssue(
                code=ValidationIssueCode.MISSING_REQUIRED_PREDICATE,
                field=rule.field_id,
                severity=IssueSeverity.BLOCKING,
                message=(
                    f"Mandatory filter required: " f"{rule.field_id!r} {rule.op} {rule.value!r}"
                ),
                correction_hint=(
                    f"Add a predicate with field={rule.field_id!r}, "
                    f"op={rule.op!r}, value={rule.value!r}."
                ),
            )
        )

    def _check_operational_rule(
        self,
        rule: OperationalRule,
        intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent,
        issues: list[ValidationIssue],
    ) -> None:
        """Check operational constraints (e.g., enforce_limit)."""
        if rule.enforce_limit is None:
            return

        if not isinstance(intent, QueryIntent):
            return

        if intent.limit is None or intent.limit > rule.enforce_limit:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.CARDINALITY_EXCEEDED,
                    field=None,
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"Query limit ({intent.limit}) exceeds "
                        f"enforced maximum ({rule.enforce_limit}). "
                        f"Results will be capped at {rule.enforce_limit}."
                    ),
                    correction_hint=f"Set limit to {rule.enforce_limit} or less.",
                )
            )
