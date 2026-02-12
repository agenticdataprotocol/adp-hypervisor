"""
PostgreSQL backend implementation.

Uses asyncpg for async connection pooling.
"""

import logging
import urllib.parse
from typing import Any

import asyncpg

from adp_hypervisor.manifest.physical import BackendDefinition, RDBMSBackendConfig
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.rdbms.backend import RDBMSBackend

logger = logging.getLogger(__name__)


class PostgresBackend(RDBMSBackend):
    """PostgreSQL backend using asyncpg connection pool."""

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
        logger.info("Connecting to PostgreSQL: %s", self.backend_id)
        self._pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
        logger.info("PostgreSQL pool created for %s", self.backend_id)

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed for %s", self.backend_id)

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
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise ConnectionError(
                f"PostgreSQL backend {self.backend_id!r} is not connected. " "Call connect() first."
            )
        return self._pool

    def _resolve_dsn(self) -> str:
        """Build the DSN (Data Source Name), resolving credentials if configured."""
        config = self._definition.config
        if not isinstance(config, RDBMSBackendConfig):
            raise TypeError(f"Expected RDBMSBackendConfig, got {type(config).__name__!r}")
        dsn = config.uri
        if self._definition.credentials is not None:
            try:
                password = resolve_credential(self._definition.credentials)
                dsn = _inject_password(dsn, password)
            except CredentialResolutionError:
                logger.warning(
                    "Could not resolve credentials for %s, using URI as-is",
                    self.backend_id,
                )
        return dsn

    def _schema_name(self) -> str:
        """Return the database schema to query, defaulting to ``public``."""
        config = self._definition.config
        if not isinstance(config, RDBMSBackendConfig):
            raise TypeError(f"Expected RDBMSBackendConfig, got {type(config).__name__!r}")
        return config.schema_name or "public"


def _inject_password(dsn: str, password: str) -> str:
    """Inject *password* into a PostgreSQL DSN.

    Uses ``urllib.parse`` to safely handle special characters in passwords
    and complex DSN formats.
    """
    parsed = urllib.parse.urlparse(dsn)
    if not parsed.scheme or not parsed.hostname:
        return dsn
    replaced = parsed._replace(
        netloc=f"{urllib.parse.quote(parsed.username or '', safe='')}"
        f":{urllib.parse.quote(password, safe='')}"
        f"@{parsed.hostname}"
        f"{f':{parsed.port}' if parsed.port else ''}"
    )
    return urllib.parse.urlunparse(replaced)
