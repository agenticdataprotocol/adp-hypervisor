"""
Vector Backend base class.

Extends the RDBMS backend with vector similarity search support via the
SIMILAR operator.  Subclasses (e.g., PgVectorBackend) supply connection
management and may override dialect-specific hook methods for distance
operators.
"""

import logging
from typing import Any

from adp_hypervisor.protocol.types import (
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    SimilarValue,
)
from backends.rdbms.backend import RDBMSBackend

logger = logging.getLogger(__name__)


# Mapping from ADP distance function names to pgvector-style SQL operators.
_DISTANCE_OP_MAP: dict[str, str] = {
    "COSINE": "<=>",
    "L2": "<->",
    "INNER_PRODUCT": "<#>",
}

_DEFAULT_DISTANCE_FUNCTION = "COSINE"


class VectorBackend(RDBMSBackend):
    """Base class for vector-capable backends.

    Inherits all RDBMS query/lookup translation from ``RDBMSBackend`` and adds
    support for the ``SIMILAR`` predicate operator, which is translated into a
    vector distance ``ORDER BY`` clause.
    """

    # ------------------------------------------------------------------
    # Hook methods — subclasses may override
    # ------------------------------------------------------------------

    def distance_operator(self, distance_function: str | None) -> str:
        """Return the SQL distance operator for the given function name.

        Args:
            distance_function: One of ``COSINE``, ``L2``, ``INNER_PRODUCT``,
                or ``None`` (defaults to ``COSINE``).

        Returns:
            The SQL operator string (e.g., ``<=>``).

        Raises:
            ValueError: If the distance function is not supported.
        """
        fn = (distance_function or _DEFAULT_DISTANCE_FUNCTION).upper()
        op = _DISTANCE_OP_MAP.get(fn)
        if op is None:
            raise ValueError(
                f"Unsupported distance function: {fn!r}. "
                f"Supported: {', '.join(_DISTANCE_OP_MAP)}"
            )
        return op

    def cast_vector(self, placeholder: str) -> str:
        """Wrap a parameter placeholder with a vector type cast.

        Default returns ``<placeholder>::vector`` (PostgreSQL / pgvector).

        Args:
            placeholder: The SQL parameter placeholder (e.g., ``$2``).

        Returns:
            The casted placeholder string.
        """
        return f"{placeholder}::vector"

    # ------------------------------------------------------------------
    # SIMILAR-aware query builder (overrides RDBMSBackend)
    # ------------------------------------------------------------------

    def _build_query_sql(self, source: str, intent: QueryIntent) -> tuple[str, list[Any]]:
        """Build SQL for a QUERY intent, handling SIMILAR predicates.

        SIMILAR predicates are extracted from the predicate tree and turned
        into an ``ORDER BY <col> <distance_op> <vector>`` clause instead of
        appearing in the ``WHERE`` clause.
        """
        similar_preds, remaining_group = self._extract_similar(intent.predicates)

        if not similar_preds:
            return super()._build_query_sql(source, intent)

        # TODO: OR + SIMILAR semantics may be useful (e.g., "match A OR find
        #  nearest neighbors"). Requires design discussion on SQL translation
        #  strategy (UNION, CTEs, etc.) before support can be added.
        if intent.predicates.op.value == "OR":
            raise ValueError("SIMILAR predicates are not supported inside OR groups")

        similar_values = [self._parse_similar_value(p) for p in similar_preds]
        params: list[Any] = []
        projections = self._build_select(intent.projections)
        table = self.quote_identifier(source)

        # WHERE from remaining (non-SIMILAR) predicates
        where = self._build_where(remaining_group, params)

        sql = f"SELECT {projections} FROM {table}"
        if where:
            sql += f" WHERE {where}"

        # Threshold filters and ORDER BY parts for each SIMILAR predicate
        order_parts: list[str] = []
        for pred, sv in zip(similar_preds, similar_values, strict=True):
            assert sv.vector is not None  # guaranteed by _parse_similar_value
            params.append(self._format_vector(sv.vector))
            vector_ph = self.placeholder(len(params))

            col = self.quote_identifier(pred.field_id)
            dist_op = self.distance_operator(sv.distance_function)
            order_expr = f"{col} {dist_op} {self.cast_vector(vector_ph)}"
            order_parts.append(order_expr)

            if sv.threshold is not None:
                params.append(sv.threshold)
                threshold_ph = self.placeholder(len(params))
                conjunction = " AND " if where or "WHERE" in sql else " WHERE "
                sql += f"{conjunction}{order_expr} < {threshold_ph}"
                where = where or "applied"

        sql += f" ORDER BY {', '.join(order_parts)}"

        limit = self._resolve_similar_limit(similar_values, intent.limit)
        if limit is not None:
            sql += f" {self.build_limit_clause(limit)}"

        return sql, params

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_similar(
        group: PredicateGroup,
    ) -> tuple[list[Predicate], PredicateGroup]:
        """Extract all SIMILAR predicates from a predicate group.

        Returns a tuple of ``(similar_predicates, remaining_group)`` where
        ``remaining_group`` contains all predicates except the extracted ones.

        Only top-level predicates are checked; nested groups are left intact.
        """
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

    @staticmethod
    def _format_vector(vector: list[float]) -> str:
        """Format a float list as a pgvector literal string, e.g. ``'[0.1,0.2,0.3]'``."""
        return "[" + ",".join(str(v) for v in vector) + "]"
