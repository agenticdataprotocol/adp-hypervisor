"""
NoSQL Backend base class.

Provides template methods for translating ADP Intents into NoSQL queries.
Subclasses supply connection management and dialect-specific implementations.
"""

import logging
import re
from abc import abstractmethod
from typing import Any

from adp_hypervisor.manifest.index import get_global_manifest_index
from adp_hypervisor.manifest.physical import BackendDefinition
from adp_hypervisor.protocol.types import (
    Field,
    IngestIntent,
    Intent,
    IssueSeverity,
    LogicOperator,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
    ValidationIssue,
    ValidationIssueCode,
)
from backends.base import Backend, BackendResult

logger = logging.getLogger(__name__)


class NOSQLBackend(Backend):
    """Base class for NoSQL backends.

    Implements generic Intent → NoSQL query translation using the Template Method pattern.
    Subclasses must implement connection management, schema discovery, and query execution.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)

    # -------------------------------------------------------------------------
    # Abstract methods — subclasses must implement
    # -------------------------------------------------------------------------

    @abstractmethod
    async def fetch_documents(
        self,
        collection: str,
        filter_query: dict[str, Any],
        projection: dict[str, Any] | None,
        sort: list[tuple[str, int]] | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Execute a query and return documents.

        Args:
            collection: The collection/table name.
            filter_query: The filter/query dict.
            projection: Field projection dict (None for all fields).
            sort: List of (field, direction) tuples.
            limit: Maximum number of documents to return.

        Returns:
            List of documents as dicts.
        """

    @abstractmethod
    async def get_schema(self, source: str) -> list[Field]:
        """Discover the schema for a collection.

        Args:
            source: The source identifier (collection name).

        Returns:
            A list of field definitions describing the source schema.
        """

    # -------------------------------------------------------------------------
    # Hook methods — subclasses may override for dialect differences
    # -------------------------------------------------------------------------

    def translate_sort_direction(self, direction: str) -> int:
        """Translate ADP sort direction to backend-specific value.

        Args:
            direction: "ASC" or "DESC".

        Returns:
            Backend-specific sort direction (1 for ASC, -1 for DESC in MongoDB).
        """
        return 1 if direction == "ASC" else -1

    # -------------------------------------------------------------------------
    # Intent → Query translation (Template Method)
    # -------------------------------------------------------------------------

    def _build_lookup_query(self, intent: LookupIntent) -> dict[str, Any]:
        """Translate LOOKUP intent to filter dict.

        Args:
            intent: The LOOKUP intent.

        Returns:
            Filter dict for the lookup query.
        """
        return {intent.key.field_id: intent.key.value}

    def _build_query_filter(self, group: PredicateGroup) -> dict[str, Any]:
        """Translate QUERY predicates to filter dict.

        Args:
            group: The predicate group to translate.

        Returns:
            Filter dict for the query.
        """
        parts: list[dict[str, Any]] = []

        for pred in group.predicates:
            if isinstance(pred, PredicateGroup):
                nested = self._build_query_filter(pred)
                if nested:
                    parts.append(nested)
            elif isinstance(pred, Predicate):
                parts.append(self._translate_predicate(pred))

        if not parts:
            return {}

        # Handle logic operators
        if group.op == LogicOperator.AND:
            if len(parts) == 1:
                return parts[0]
            return {"$and": parts}
        elif group.op == LogicOperator.OR:
            if len(parts) == 1:
                return parts[0]
            return {"$or": parts}
        elif group.op == LogicOperator.NOT:
            if len(parts) == 1:
                return {"$nor": parts}
            return {"$nor": parts}

        return {}

    def _translate_predicate(self, pred: Predicate) -> dict[str, Any]:
        """Translate single predicate to query operator.

        Args:
            pred: The predicate to translate.

        Returns:
            Query dict for the predicate.

        Raises:
            ValueError: If the operator is not supported or value is invalid.
        """
        field = pred.field_id
        op = pred.op
        value = pred.value

        # Handle IN operator
        if op == PredicateOperator.IN:
            if not isinstance(value, list):
                raise ValueError(f"IN operator requires a list value, got {type(value).__name__}")
            if not value:
                raise ValueError("IN operator requires a non-empty list")
            return {field: {"$in": value}}

        # Handle CONTAINS operator (substring search for strings)
        if op == PredicateOperator.CONTAINS:
            escaped = re.escape(str(value))
            return {field: {"$regex": escaped, "$options": "i"}}

        # Handle LIKE / ILIKE operator (pattern matching)
        if op in (PredicateOperator.LIKE, PredicateOperator.ILIKE):
            pattern = _like_to_regex(str(value))
            if op == PredicateOperator.ILIKE:
                return {field: {"$regex": pattern, "$options": "i"}}
            return {field: {"$regex": pattern}}

        # Handle standard comparison operators
        mongo_op = _OPERATOR_MAP.get(op)
        if mongo_op is None:
            raise ValueError(f"Unsupported predicate operator for NoSQL: {op}")

        return {field: {mongo_op: value}}

    def _build_projection(self, projections: list[str] | None) -> dict[str, Any] | None:
        """Build projection dict from field list.

        Args:
            projections: List of field names to project, or None for all fields.

        Returns:
            Projection dict, or None for all fields.
        """
        if not projections:
            return None

        # Build projection dict
        projection = {field: 1 for field in projections}

        # MongoDB includes _id by default, so explicitly exclude it if not requested
        if "_id" not in projections:
            projection["_id"] = 0

        return projection

    def _build_sort(self, order_by: list[Any] | None) -> list[tuple[str, int]] | None:
        """Build sort list from order_by specification.

        Args:
            order_by: List of SortOrder objects, or None.

        Returns:
            List of (field, direction) tuples, or None.
        """
        if not order_by:
            return None
        return [(s.field_id, self.translate_sort_direction(s.direction)) for s in order_by]

    # -------------------------------------------------------------------------
    # Backend interface implementation
    # -------------------------------------------------------------------------

    async def validate(self, intent: Intent) -> list[ValidationIssue]:
        """Validate an intent by building the query without executing it.

        Args:
            intent: The intent to validate.

        Returns:
            A list of validation issues. An empty list means the intent is valid.
        """
        try:
            manifest_index = get_global_manifest_index()
            resource = manifest_index.get_resource(intent.resource_id)
            if resource is None:
                raise ValueError(
                    f"Resource not found for intent.resource_id={intent.resource_id!r}"
                )
            source = resource.source_definition.source
            if not source:
                raise ValueError(f"Resource {resource.resource_id!r} has no source definitions")
            self._intent_to_query(source, intent)
        except Exception as exc:
            return [
                ValidationIssue(
                    code=ValidationIssueCode.INVALID_FORMAT,
                    severity=IssueSeverity.BLOCKING,
                    message=str(exc),
                )
            ]
        return []

    async def execute(self, intent: Intent) -> BackendResult:
        """Translate intent to query and execute it.

        Args:
            intent: The intent to execute.

        Returns:
            The execution result containing rows and optional metadata.
        """
        manifest_index = get_global_manifest_index()
        resource = manifest_index.get_resource(intent.resource_id)
        if resource is None:
            raise ValueError(f"Resource not found for intent.resource_id={intent.resource_id!r}")
        source = resource.source_definition.source
        if not source:
            raise ValueError(f"Resource {resource.resource_id!r} has no source definitions")
        filter_query, projection, sort, limit = self._intent_to_query(source, intent)
        logger.debug(
            "Executing query on %s: filter=%s, projection=%s, sort=%s, limit=%s",
            source,
            filter_query,
            projection,
            sort,
            limit,
        )
        rows = await self.fetch_documents(source, filter_query, projection, sort, limit)
        return BackendResult(rows=rows)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _intent_to_query(
        self, source: str, intent: Intent
    ) -> tuple[dict[str, Any], dict[str, Any] | None, list[tuple[str, int]] | None, int | None]:
        """Translate intent to query components.

        Args:
            source: The source identifier.
            intent: The intent to translate.

        Returns:
            Tuple of (filter_query, projection, sort, limit).

        Raises:
            NotImplementedError: If the intent type is not supported.
            ValueError: If the intent type is unknown.
        """
        if isinstance(intent, LookupIntent):
            filter_query = self._build_lookup_query(intent)
            projection = self._build_projection(intent.projections)
            return filter_query, projection, None, None

        elif isinstance(intent, QueryIntent):
            filter_query = self._build_query_filter(intent.predicates)
            projection = self._build_projection(intent.projections)
            sort = self._build_sort(intent.order_by)
            limit = intent.limit
            return filter_query, projection, sort, limit

        elif isinstance(intent, (IngestIntent, ReviseIntent)):
            raise NotImplementedError(
                f"{intent.intent_class} is not yet supported for NoSQL backends"
            )

        raise ValueError(f"Unknown intent type: {type(intent).__name__}")


def _like_to_regex(pattern: str) -> str:
    """Convert a SQL LIKE pattern to a MongoDB-compatible regex.

    Splits on SQL wildcards (``%`` and ``_``), escapes regex metacharacters
    in the literal segments, then reassembles with regex equivalents and anchors.

    Args:
        pattern: The SQL LIKE pattern.

    Returns:
        An anchored regex string equivalent to the LIKE pattern.
    """
    # Split pattern into tokens: literal parts and wildcards
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "%":
            parts.append(".*")
            i += 1
        elif pattern[i] == "_":
            parts.append(".")
            i += 1
        else:
            # Collect consecutive literal characters
            j = i
            while j < len(pattern) and pattern[j] not in ("%", "_"):
                j += 1
            parts.append(re.escape(pattern[i:j]))
            i = j
    return "^" + "".join(parts) + "$"


# Mapping from ADP PredicateOperator to MongoDB query operators.
_OPERATOR_MAP: dict[PredicateOperator, str] = {
    PredicateOperator.EQ: "$eq",
    PredicateOperator.NEQ: "$ne",
    PredicateOperator.GT: "$gt",
    PredicateOperator.LT: "$lt",
    PredicateOperator.GTE: "$gte",
    PredicateOperator.LTE: "$lte",
}
