"""Integration tests for the PostgreSQL backend.

Uses testcontainers to spin up a real PostgreSQL instance and exercises
connect, LOOKUP, and QUERY intents end-to-end.
"""

import pytest
from testcontainers.postgres import PostgresContainer

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    RDBMSBackendConfig,
)
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
# Fixtures
# =============================================================================

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


@pytest.fixture(scope="module")
def pg_container():
    """Start a PostgreSQL container for the test module."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="module")
def backend_definition(pg_container) -> BackendDefinition:
    url = pg_container.get_connection_url()
    # testcontainers returns a SQLAlchemy-style URL (e.g. postgresql+psycopg2://...);
    # asyncpg requires a plain postgresql:// scheme.
    dsn = url.split("://", 1)[-1]
    dsn = f"postgresql://{dsn}"
    return BackendDefinition(
        id="test_pg",
        type=BackendType.RDBMS,
        config=RDBMSBackendConfig(uri=dsn),
    )


@pytest.fixture()
async def backend(backend_definition, pg_container):
    """Create, connect, seed, and yield a PostgresBackend; disconnect on teardown."""
    be = PostgresBackend(definition=backend_definition)
    await be.connect()

    # Seed the test table
    pool = be._pool
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS users")
        await conn.execute(_TABLE_DDL)

    yield be
    await be.disconnect()


# =============================================================================
# Connection Tests
# =============================================================================


class TestConnection:
    async def test_connect_and_disconnect(self, backend_definition):
        be = PostgresBackend(definition=backend_definition)
        await be.connect()
        assert be._pool is not None
        await be.disconnect()
        assert be._pool is None

    async def test_disconnect_when_not_connected(self, backend_definition):
        be = PostgresBackend(definition=backend_definition)
        await be.disconnect()  # should not raise


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent:
    async def test_lookup_by_id(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="id", value=1),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 1
        assert result.rows[0]["name"] == "Alice"

    async def test_lookup_with_projections(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="id", value=2),
            projections=["name"],
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 1
        assert result.rows[0]["name"] == "Bob"
        assert "age" not in result.rows[0]

    async def test_lookup_not_found(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="id", value=999),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 0


# =============================================================================
# QUERY Intent Tests
# =============================================================================


class TestQueryIntent:
    async def test_query_all(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 3

    async def test_query_with_filter(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2
        names = {row["name"] for row in result.rows}
        assert names == {"Alice", "Charlie"}

    async def test_query_with_order_and_limit(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
            order_by=[SortOrder(field_id="age", direction="ASC")],
            limit=2,
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2
        assert result.rows[0]["name"] == "Bob"
        assert result.rows[1]["name"] == "Alice"

    async def test_query_with_projections(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
            projections=["name", "age"],
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 1
        assert result.rows[0]["name"] == "Charlie"
        assert result.rows[0]["age"] == 35
        assert "id" not in result.rows[0]

    async def test_query_in_operator(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=["Alice", "Bob"]),
                ],
            ),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2

    async def test_query_in_empty_list_raises(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=[]),
                ],
            ),
        )
        with pytest.raises(ValueError, match="non-empty list"):
            await backend.execute("users", intent)

    async def test_query_contains_substring(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="li"),
                ],
            ),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2
        names = {row["name"] for row in result.rows}
        assert names == {"Alice", "Charlie"}

    async def test_query_or_predicates(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="OR",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2
        names = {row["name"] for row in result.rows}
        assert names == {"Alice", "Charlie"}

    async def test_query_nested_predicates(self, backend):
        intent = QueryIntent(
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
        result = await backend.execute("users", intent)
        assert len(result.rows) == 2
        names = {row["name"] for row in result.rows}
        assert names == {"Alice", "Bob"}


# =============================================================================
# Validate Tests
# =============================================================================


class TestValidate:
    async def test_validate_valid_lookup(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="id", value=1),
        )
        issues = await backend.validate("users", intent)
        assert issues == []

    async def test_validate_valid_query(self, backend):
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=20),
                ],
            ),
        )
        issues = await backend.validate("users", intent)
        assert issues == []


# =============================================================================
# Unsupported Intent Tests
# =============================================================================


class TestUnsupportedIntents:
    async def test_ingest_not_supported(self, backend):
        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        with pytest.raises(NotImplementedError, match="INGEST"):
            await backend.execute("users", intent)

    async def test_revise_not_supported(self, backend):
        intent = ReviseIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="id", op=PredicateOperator.EQ, value=1),
                ],
            ),
            payload={"name": "Updated"},
        )
        with pytest.raises(NotImplementedError, match="REVISE"):
            await backend.execute("users", intent)

    async def test_validate_ingest_returns_issue(self, backend):
        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        issues = await backend.validate("users", intent)
        assert len(issues) == 1
        assert issues[0].severity == "BLOCKING"
