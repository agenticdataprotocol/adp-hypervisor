"""Integration tests for the PostgreSQL backend.

Uses testcontainers to spin up a real PostgreSQL instance and exercises
connect, LOOKUP, and QUERY intents end-to-end.
"""

import unittest
from unittest.mock import patch

from testcontainers.postgres import PostgresContainer

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    RDBMSBackendConfig,
)
from adp_hypervisor.manifest.semantic import CuratedResource
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    IngestIntent,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
    SortOrder,
)
from backends.rdbms.postgres import PostgresBackend

# =============================================================================
# Module-level fixtures
# =============================================================================

_RESOURCE_ID = "test:users"

_TABLE_DDL = """
CREATE TABLE users (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    age  INTEGER NOT NULL
);
INSERT INTO users (name, age) VALUES
    ('Alice', 30),
    ('Bob', 25),
    ('Charlie', 35);
"""

_pg_container: PostgresContainer | None = None
_backend_definition: BackendDefinition | None = None


def setUpModule() -> None:
    """Start a PostgreSQL container for the test module."""
    global _pg_container, _backend_definition  # noqa: PLW0603
    _pg_container = PostgresContainer("postgres:16-alpine")
    _pg_container.start()
    url = _pg_container.get_connection_url()
    # testcontainers returns a SQLAlchemy-style URL (e.g. postgresql+psycopg2://...);
    # asyncpg requires a plain postgresql:// scheme.
    dsn = url.split("://", 1)[-1]
    dsn = f"postgresql://{dsn}"
    _backend_definition = BackendDefinition(
        id="test_pg",
        type=BackendType.RDBMS,
        provider="postgresql",
        config=RDBMSBackendConfig(uri=dsn),
    )


def tearDownModule() -> None:
    """Stop the PostgreSQL container."""
    global _pg_container  # noqa: PLW0603
    if _pg_container is not None:
        _pg_container.stop()
        _pg_container = None


# =============================================================================
# Helpers
# =============================================================================


def _get_backend_definition() -> BackendDefinition:
    """Return the module-level backend definition, raising if not initialised."""
    if _backend_definition is None:
        raise RuntimeError("setUpModule was not called")
    return _backend_definition


def _make_resource() -> CuratedResource:
    """Return a minimal CuratedResource bound to the users table."""
    backend_def = _get_backend_definition()
    return CuratedResource.model_validate(
        {
            "resourceId": _RESOURCE_ID,
            "intentClasses": ["*"],
            "backendId": backend_def.id,
            "version": 1,
            "sourceDefinition": {
                "source": "users",
            },
        }
    )


class _TestManifestIndex:
    """Minimal stub manifest index exposing get_resource for this test module."""

    def __init__(self) -> None:
        self._resource = _make_resource()

    def get_resource(self, resource_id: str) -> CuratedResource | None:
        if resource_id == self._resource.resource_id:
            return self._resource
        return None


class _SeededBackendMixin(unittest.IsolatedAsyncioTestCase):
    """Base that creates, seeds, and tears down a PostgresBackend per test."""

    backend: PostgresBackend

    async def asyncSetUp(self) -> None:
        self._manifest_patch = patch(
            "backends.rdbms.backend.get_global_manifest_index",
            return_value=_TestManifestIndex(),
        )
        self._manifest_patch.start()
        self.backend = PostgresBackend(definition=_get_backend_definition())
        await self.backend.connect()
        pool = self.backend._pool
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS users")
            await conn.execute(_TABLE_DDL)

    async def asyncTearDown(self) -> None:
        await self.backend.disconnect()
        self._manifest_patch.stop()


# =============================================================================
# Connection Tests
# =============================================================================


class TestConnection(unittest.IsolatedAsyncioTestCase):
    async def test_connect_and_disconnect(self) -> None:
        be = PostgresBackend(definition=_get_backend_definition())
        await be.connect()
        self.assertIsNotNone(be._pool)
        await be.disconnect()
        self.assertIsNone(be._pool)

    async def test_disconnect_when_not_connected(self) -> None:
        be = PostgresBackend(definition=_get_backend_definition())
        await be.disconnect()  # should not raise


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent(_SeededBackendMixin):
    async def test_lookup_by_id(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="id", value=1),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")

    async def test_lookup_with_projections(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="id", value=2),
            projections=["name"],
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Bob")
        self.assertNotIn("age", result.rows[0])

    async def test_lookup_not_found(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="id", value=999),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 0)


# =============================================================================
# QUERY Intent Tests
# =============================================================================


class TestQueryIntent(_SeededBackendMixin):
    async def test_query_all(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 3)

    async def test_query_with_filter(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_with_order_and_limit(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
            order_by=[SortOrder(field_id="age", direction="ASC")],
            limit=2,
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.rows[0]["name"], "Bob")
        self.assertEqual(result.rows[1]["name"], "Alice")

    async def test_query_with_projections(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
            projections=["name", "age"],
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Charlie")
        self.assertEqual(result.rows[0]["age"], 35)
        self.assertNotIn("id", result.rows[0])

    async def test_query_in_operator(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=["Alice", "Bob"]),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)

    async def test_query_in_empty_list_raises(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=[]),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            await self.backend.execute(intent)

    async def test_query_contains_substring(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="li"),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_or_predicates(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="OR",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_nested_predicates(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=25),
                    PredicateGroup(
                        op="OR",
                        predicates=[
                            Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                            Predicate(field_id="name", op=PredicateOperator.EQ, value="Bob"),
                        ],
                    ),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Bob"})


# =============================================================================
# Unsupported Intent Tests
# =============================================================================


class TestUnsupportedIntents(_SeededBackendMixin):
    async def test_ingest_not_supported(self) -> None:
        intent = IngestIntent(resource_id=_RESOURCE_ID, payload=[{"name": "Dave", "age": 40}])
        with self.assertRaisesRegex(NotImplementedError, "INGEST"):
            await self.backend.execute(intent)

    async def test_revise_not_supported(self) -> None:
        intent = ReviseIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="id", op=PredicateOperator.EQ, value=1),
                ],
            ),
            payload={"name": "Updated"},
        )
        with self.assertRaisesRegex(NotImplementedError, "REVISE"):
            await self.backend.execute(intent)
