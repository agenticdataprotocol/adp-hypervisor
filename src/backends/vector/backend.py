"""
Vector Backend abstract base class.

Defines the abstract interface for vector-capable backends and provides
protocol-level helpers for working with SIMILAR predicates.  Subclasses
(e.g., PgVectorBackend) supply connection management, query execution,
and database-specific translation logic.
"""

import logging

from adp_hypervisor.protocol.types import (
    Predicate,
    PredicateExpression,
    PredicateGroup,
    PredicateOperator,
    SimilarValue,
    normalize_to_predicate_group,
)
from backends.base import Backend

logger = logging.getLogger(__name__)


class VectorBackend(Backend):
    """Abstract base class for vector-capable backends.

    Provides protocol-level helpers for extracting and validating SIMILAR
    predicates from ADP intent predicate trees.  Concrete subclasses must
    implement ``connect``, ``disconnect``, and ``execute`` (inherited from
    ``Backend``), translating intents into the appropriate query language
    for their vector store.
    """

    # ------------------------------------------------------------------
    # Protocol-level helpers for SIMILAR predicates
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_similar(
        expr: PredicateExpression,
    ) -> tuple[list[Predicate], PredicateGroup]:
        """Extract all SIMILAR predicates from a predicate expression.

        Returns a tuple of ``(similar_predicates, remaining_group)`` where
        ``remaining_group`` contains all predicates except the extracted ones.

        Only top-level predicates are checked; nested groups are left intact.
        """
        group = normalize_to_predicate_group(expr)
        similar_preds: list[Predicate] = []
        remaining: list[PredicateGroup | Predicate] = []
        for pred in group.predicates:
            if isinstance(pred, Predicate) and pred.op == PredicateOperator.SIMILAR:
                similar_preds.append(pred)
            else:
                remaining.append(pred)
        return similar_preds, PredicateGroup(op=group.op, predicates=remaining)

    @staticmethod
    def _resolve_similar_limit(
        similar_values: list[SimilarValue], intent_limit: int | None
    ) -> int | None:
        """Determine the effective LIMIT from SIMILAR ``top`` values.

        Args:
            similar_values: Parsed SimilarValue objects from SIMILAR predicates.
            intent_limit: The limit from the QueryIntent, used as fallback.

        Returns:
            The resolved limit, or ``None`` if no limit is specified.

        Raises:
            ValueError: If multiple SIMILAR predicates specify different
                ``top`` values.
        """
        tops = {sv.top for sv in similar_values if sv.top is not None}
        if len(tops) > 1:
            raise ValueError(f"Multiple SIMILAR predicates specify conflicting top values: {tops}")
        if tops:
            return tops.pop()
        return intent_limit

    @staticmethod
    def _parse_similar_value(pred: Predicate) -> SimilarValue:
        """Validate and return the ``SimilarValue`` from a SIMILAR predicate.

        Raises:
            ValueError: If the predicate value is not a ``SimilarValue`` or
                has no ``vector`` field set.
        """
        if not isinstance(pred.value, SimilarValue):
            raise ValueError(
                f"SIMILAR predicate requires a SimilarValue, got {type(pred.value).__name__}"
            )
        if pred.value.vector is None:
            raise ValueError("SimilarValue.vector must be set for vector similarity search")
        return pred.value
