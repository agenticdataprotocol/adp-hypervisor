"""
pgvector backend implementation.

Combines RDBMS SQL translation with vector similarity search support via
the pgvector PostgreSQL extension.  Uses asyncpg for async connection pooling.
"""

import logging
import urllib.parse
from typing import Any

import asyncpg

from adp_hypervisor.manifest.physical import BackendDefinition, VectorBackendConfig
from adp_hypervisor.protocol.types import (
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    normalize_to_predicate_group,
)
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.rdbms.backend import RDBMSBackend
from backends.vector.backend import VectorBackend

logger = logging.getLogger(__name__)

# Mapping from ADP distance function names to pgvector SQL operators.
_DISTANCE_OP_MAP: dict[str, str] = {
    "COSINE": "<=>",
    "L2": "<->",
    "INNER_PRODUCT": "<#>",
}

_DEFAULT_DISTANCE_FUNCTION = "COSINE"

# SQL expressions that convert a similarity threshold (0.0–1.0, higher = more
# similar) into the corresponding distance ceiling for each pgvector operator.
# {ph} is replaced with the parameter placeholder at query-build time.
_THRESHOLD_EXPR: dict[str, str] = {
    "COSINE": "(1.0 - {ph})",
    "L2": "{ph}",
    "INNER_PRODUCT": "(-{ph})",
}


class PgVectorBackend(RDBMSBackend, VectorBackend):
    """pgvector backend using asyncpg connection pool.

    Inherits SQL translation from ``RDBMSBackend`` and protocol-level vector
    helpers from ``VectorBackend``.  Overrides ``_build_query_sql`` to handle
    ``SIMILAR`` predicates via pgvector distance operators.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
        self._pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create an asyncpg connection pool.

        Raises:
            ConnectionError: If the connection cannot be established.
        """
        dsn = self._resolve_dsn()
        logger.info("Connecting to pgvector: %s", self.backend_id)
        self._pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
        logger.info("pgvector pool created for %s", self.backend_id)

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("pgvector pool closed for %s", self.backend_id)

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def fetch_all(self, sql: str, params: list[Any], source: str) -> list[dict[str, Any]]:
        """Execute *sql* and return rows as a list of dicts.

        Args:
            sql: The SQL query string with positional parameter placeholders.
            params: The parameter values to bind to the query.
            source: The source (table) name, for logging or error context.

        Returns:
            A list of rows, each represented as a field-value mapping.
        """
        pool = self._require_pool()
        rows = await pool.fetch(sql, *params)
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # pgvector hook methods
    # ------------------------------------------------------------------

    def distance_operator(self, distance_function: str | None) -> str:
        """Return the pgvector SQL distance operator for the given function name.

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
        """Wrap a parameter placeholder with a pgvector type cast.

        Args:
            placeholder: The SQL parameter placeholder (e.g., ``$2``).

        Returns:
            The casted placeholder string (e.g., ``$2::vector``).
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
        pred_group = normalize_to_predicate_group(intent.predicates)
        similar_preds, remaining_group = self._extract_similar(pred_group)

        # Reject SIMILAR predicates nested inside sub-groups — only top-level
        # SIMILAR predicates are supported.
        self._reject_nested_similar(pred_group)

        if not similar_preds:
            return super()._build_query_sql(source, intent)

        if pred_group.op.value == "OR":
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
            fn = (sv.distance_function or _DEFAULT_DISTANCE_FUNCTION).upper()
            dist_op = self.distance_operator(sv.distance_function)
            order_expr = f"{col} {dist_op} {self.cast_vector(vector_ph)}"
            order_parts.append(order_expr)

            if sv.threshold is not None:
                params.append(sv.threshold)
                threshold_ph = self.placeholder(len(params))
                distance_ceiling = _THRESHOLD_EXPR[fn].format(ph=threshold_ph)
                conjunction = " AND " if where else " WHERE "
                sql += f"{conjunction}{order_expr} < {distance_ceiling}"
                where = where or "applied"

        # Append intent.order_by as secondary sort keys after distance ordering
        if intent.order_by:
            order_parts.append(self._build_order_by(intent.order_by))

        sql += f" ORDER BY {', '.join(order_parts)}"

        limit = self._resolve_similar_limit(similar_values, intent.limit)
        if limit is not None:
            sql += f" {self.build_limit_clause(limit)}"

        return sql, params

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reject_nested_similar(group: PredicateGroup) -> None:
        """Raise ``ValueError`` if any SIMILAR predicate is nested inside a sub-group."""
        for pred in group.predicates:
            if isinstance(pred, PredicateGroup):
                for child in pred.predicates:
                    if isinstance(child, Predicate) and child.op == PredicateOperator.SIMILAR:
                        raise ValueError(
                            "SIMILAR predicates must be at the top level of the predicate tree"
                        )
                # Recurse deeper
                PgVectorBackend._reject_nested_similar(pred)

    @staticmethod
    def _format_vector(vector: list[float]) -> str:
        """Format a float list as a pgvector literal string, e.g. ``'[0.1,0.2,0.3]'``."""
        return "[" + ",".join(str(v) for v in vector) + "]"

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise ConnectionError(
                f"pgvector backend {self.backend_id!r} is not connected. Call connect() first."
            )
        return self._pool

    def _resolve_dsn(self) -> str:
        """Build the DSN, resolving credentials if configured."""
        config = self._definition.config
        if not isinstance(config, VectorBackendConfig):
            raise TypeError(f"Expected VectorBackendConfig, got {type(config).__name__!r}")
        dsn = config.endpoint or ""
        if self._definition.credentials is not None:
            try:
                password = resolve_credential(self._definition.credentials)
                dsn = _inject_password(dsn, password)
            except CredentialResolutionError:
                logger.warning(
                    "Could not resolve credentials for %s, using endpoint as-is",
                    self.backend_id,
                )
        return dsn


def _inject_password(dsn: str, password: str) -> str:
    """Inject *password* into a PostgreSQL DSN.

    Uses ``urllib.parse`` to safely handle special characters in passwords
    and complex DSN formats.
    """
    parsed = urllib.parse.urlparse(dsn)
    if not parsed.scheme or not parsed.hostname:
        return dsn
    if parsed.username is None:
        raise ValueError(f"DSN must include a username when credentials are configured: {dsn!r}")
    replaced = parsed._replace(
        netloc=f"{urllib.parse.quote(parsed.username or '', safe='')}"
        f":{urllib.parse.quote(password, safe='')}"
        f"@{parsed.hostname}"
        f"{f':{parsed.port}' if parsed.port else ''}"
    )
    return urllib.parse.urlunparse(replaced)
