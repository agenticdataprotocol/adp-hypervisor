"""
RDBMS Backend base class.

Provides a Template Method implementation for translating ADP Intents into SQL.
Subclasses (e.g., PostgresBackend) supply connection management and may override
dialect-specific hook methods.
"""

import logging
from abc import abstractmethod
from typing import Any

from adp_hypervisor.manifest.index import get_global_manifest_index
from adp_hypervisor.manifest.physical import BackendDefinition
from adp_hypervisor.protocol.types import (
    IngestIntent,
    Intent,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
    SortOrder,
)
from backends.base import Backend, BackendResult

logger = logging.getLogger(__name__)


class RDBMSBackend(Backend):
    """Base class for RDBMS backends.

    Implements generic Intent → SQL translation using the Template Method pattern.
    Subclasses must implement connection management and schema discovery; they may
    override hook methods to handle SQL dialect differences.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)

    # -------------------------------------------------------------------------
    # Abstract methods — subclasses must implement
    # -------------------------------------------------------------------------

    @abstractmethod
    async def fetch_all(self, sql: str, params: list[Any], source: str) -> list[dict[str, Any]]:
        """Execute a SQL query and return all rows as dicts.

        Args:
            sql: The SQL query string with positional parameter placeholders.
            params: The parameter values to bind to the query.
            source: The source (table) name, for logging or error context.

        Returns:
            A list of rows, each represented as a field-value mapping.
        """

    # -------------------------------------------------------------------------
    # Hook methods — subclasses may override for dialect differences
    # -------------------------------------------------------------------------

    def quote_identifier(self, identifier: str) -> str:
        """Quote a SQL identifier (table/column name).

        Default uses double-quotes (ANSI SQL standard).

        Args:
            identifier: The raw identifier to quote.

        Returns:
            The quoted identifier string.
        """
        safe = identifier.replace('"', '""')
        return f'"{safe}"'

    def placeholder(self, index: int) -> str:
        """Return a positional parameter placeholder.

        Default uses ``$1``, ``$2``, … (PostgreSQL style).
        Override for ``%s`` (MySQL) or ``?`` (SQLite) if needed.

        Args:
            index: The 1-based parameter index.

        Returns:
            The placeholder string for the given index.
        """
        return f"${index}"

    def build_limit_clause(self, limit: int) -> str:
        """Return the SQL LIMIT clause.

        Default: ``LIMIT <n>`` (standard SQL / PostgreSQL).

        Args:
            limit: The maximum number of rows to return.

        Returns:
            The SQL LIMIT clause string.
        """
        return f"LIMIT {limit}"

    # -------------------------------------------------------------------------
    # Intent → SQL translation (Template Method)
    # -------------------------------------------------------------------------

    def _build_lookup_sql(self, source: str, intent: LookupIntent) -> tuple[str, list[Any]]:
        # params collects bind values for parameterized query placeholders ($1, $2, …)
        params: list[Any] = []
        projections = self._build_select(intent.projections)
        table = self.quote_identifier(source)
        col = self.quote_identifier(intent.key.field_id)
        params.append(intent.key.value)
        where = f"{col} = {self.placeholder(len(params))}"
        sql = f"SELECT {projections} FROM {table} WHERE {where}"
        return sql, params

    def _build_query_sql(self, source: str, intent: QueryIntent) -> tuple[str, list[Any]]:
        params: list[Any] = []
        projections = self._build_select(intent.projections)
        table = self.quote_identifier(source)
        where = self._build_where(intent.predicates, params)
        sql = f"SELECT {projections} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if intent.order_by:
            sql += f" ORDER BY {self._build_order_by(intent.order_by)}"
        if intent.limit is not None:
            sql += f" {self.build_limit_clause(intent.limit)}"
        return sql, params

    # -------------------------------------------------------------------------
    # SQL fragment builders
    # -------------------------------------------------------------------------

    def _build_select(self, projections: list[str] | None) -> str:
        if not projections:
            return "*"
        return ", ".join(self.quote_identifier(p) for p in projections)

    def _build_where(self, group: PredicateGroup, params: list[Any]) -> str:
        parts: list[str] = []
        for pred in group.predicates:
            if isinstance(pred, PredicateGroup):
                nested = self._build_where(pred, params)
                if nested:
                    parts.append(f"({nested})")
            elif isinstance(pred, Predicate):
                parts.append(self._build_predicate(pred, params))
        if not parts:
            return ""
        joiner = f" {group.op.value} "
        return joiner.join(parts)

    def _build_predicate(self, pred: Predicate, params: list[Any]) -> str:
        col = self.quote_identifier(pred.field_id)
        op = pred.op
        if op == PredicateOperator.IN:
            if not isinstance(pred.value, list):
                raise ValueError(
                    f"IN operator requires a list value, got {type(pred.value).__name__}"
                )
            if not pred.value:
                raise ValueError("IN operator requires a non-empty list")
            placeholders = []
            for v in pred.value:
                params.append(v)
                placeholders.append(self.placeholder(len(params)))
            return f"{col} IN ({', '.join(placeholders)})"
        if op == PredicateOperator.CONTAINS:
            params.append(f"%{pred.value}%")
        else:
            params.append(pred.value)
        ph = self.placeholder(len(params))
        sql_op = _OPERATOR_MAP.get(op)
        if sql_op is None:
            raise ValueError(f"Unsupported predicate operator for RDBMS: {op}")
        return f"{col} {sql_op} {ph}"

    def _build_order_by(self, order_by: list[SortOrder]) -> str:
        parts = []
        for s in order_by:
            parts.append(f"{self.quote_identifier(s.field_id)} {s.direction}")
        return ", ".join(parts)

    # -------------------------------------------------------------------------
    # Backend interface implementation
    # -------------------------------------------------------------------------

    async def execute(self, intent: Intent) -> BackendResult:
        """Translate *intent* to SQL and execute it.

        The backend resolves the concrete resource and source via the global
        ManifestIndex using ``intent.resource_id``.
        """
        manifest_index = get_global_manifest_index()
        resource = manifest_index.get_resource(intent.resource_id)
        if resource is None:
            raise ValueError(f"Resource not found for intent.resource_id={intent.resource_id!r}")
        source = resource.source_definition.source
        if not source:
            raise ValueError(f"Resource {resource.resource_id!r} has no source definitions")
        sql, params = self._intent_to_sql(source, intent)
        logger.debug("Executing SQL: %s | params=%s", sql, params)
        rows = await self.fetch_all(sql, params, source)
        return BackendResult(rows=rows)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _intent_to_sql(self, source: str, intent: Intent) -> tuple[str, list[Any]]:
        if isinstance(intent, LookupIntent):
            return self._build_lookup_sql(source, intent)
        elif isinstance(intent, QueryIntent):
            return self._build_query_sql(source, intent)
        elif isinstance(intent, (IngestIntent, ReviseIntent)):
            raise NotImplementedError(
                f"{intent.intent_class} is not yet supported for RDBMS backends"
            )
        raise ValueError(f"Unknown intent type: {type(intent).__name__}")


# Mapping from ADP PredicateOperator to SQL operators.
_OPERATOR_MAP: dict[PredicateOperator, str] = {
    PredicateOperator.EQ: "=",
    PredicateOperator.NEQ: "!=",
    PredicateOperator.GT: ">",
    PredicateOperator.LT: "<",
    PredicateOperator.GTE: ">=",
    PredicateOperator.LTE: "<=",
    PredicateOperator.CONTAINS: "LIKE",
    PredicateOperator.LIKE: "LIKE",
    PredicateOperator.ILIKE: "ILIKE",
}
