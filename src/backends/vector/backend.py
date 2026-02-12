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
        similar_pred, remaining_group = self._extract_similar(intent.predicates)

        if similar_pred is None:
            return super()._build_query_sql(source, intent)

        similar_value = self._parse_similar_value(similar_pred)
        params: list[Any] = []
        projections = self._build_select(intent.projections)
        table = self.quote_identifier(source)

        # WHERE from remaining (non-SIMILAR) predicates
        where = self._build_where(remaining_group, params)

        # Vector parameter
        params.append(similar_value.text)
        vector_ph = self.placeholder(len(params))

        col = self.quote_identifier(similar_pred.field_id)
        dist_op = self.distance_operator(similar_value.distance_function)

        sql = f"SELECT {projections} FROM {table}"
        if where:
            sql += f" WHERE {where}"

        # Threshold filter
        if similar_value.threshold is not None:
            params.append(similar_value.threshold)
            threshold_ph = self.placeholder(len(params))
            conjunction = " AND " if where else " WHERE "
            sql += f"{conjunction}{col} {dist_op} {self.cast_vector(vector_ph)} < {threshold_ph}"

        sql += f" ORDER BY {col} {dist_op} {self.cast_vector(vector_ph)}"

        # SIMILAR.top takes priority over intent.limit
        limit = similar_value.top if similar_value.top is not None else intent.limit
        if limit is not None:
            sql += f" {self.build_limit_clause(limit)}"

        return sql, params

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_similar(
        group: PredicateGroup,
    ) -> tuple[Predicate | None, PredicateGroup]:
        """Extract the first SIMILAR predicate from a predicate group.

        Returns a tuple of ``(similar_predicate, remaining_group)`` where
        ``remaining_group`` contains all predicates except the extracted one.

        Only top-level predicates are checked; nested groups are left intact.
        """
        similar: Predicate | None = None
        remaining: list[PredicateGroup | Predicate] = []
        for pred in group.predicates:
            if (
                similar is None
                and isinstance(pred, Predicate)
                and pred.op == PredicateOperator.SIMILAR
            ):
                similar = pred
            else:
                remaining.append(pred)
        return similar, PredicateGroup(op=group.op, predicates=remaining)

    @staticmethod
    def _parse_similar_value(pred: Predicate) -> SimilarValue:
        """Validate and return the ``SimilarValue`` from a SIMILAR predicate.

        Raises:
            ValueError: If the predicate value is not a ``SimilarValue`` or
                has no ``text`` field set.
        """
        if not isinstance(pred.value, SimilarValue):
            raise ValueError(
                f"SIMILAR predicate requires a SimilarValue, got {type(pred.value).__name__}"
            )
        if pred.value.text is None:
            raise ValueError("SimilarValue.text must be set for vector similarity search")
        return pred.value
