"""Integration tests for the MongoDB backend.

Uses testcontainers to spin up a real MongoDB instance and exercises
connect, LOOKUP, and QUERY intents end-to-end.
"""

import pytest
from testcontainers.mongodb import MongoDbContainer

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    NOSQLBackendConfig,
)
from adp_hypervisor.protocol.types import (
    FieldType,
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
from backends.nosql.mongodb import MongoDBBackend

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def mongo_container():
    """Start a MongoDB container for the test module."""
    with MongoDbContainer("mongo:7") as mongo:
        yield mongo


@pytest.fixture(scope="module")
def backend_definition(mongo_container) -> BackendDefinition:
    connection_url = mongo_container.get_connection_url()

    # MongoDB connection URL format: mongodb://user:pass@host:port or mongodb://user:pass@host:port/database
    # If there's a database in the URL, extract it; otherwise use "test"
    if "/" in connection_url.split("://", 1)[1]:
        # Has database in URL
        uri, database = connection_url.rsplit("/", 1)
    else:
        # No database in URL
        uri = connection_url
        database = "test"

    # NOSQLBackendConfig has extra="allow", so we can pass additional fields
    config = NOSQLBackendConfig.model_validate(
        {"type": "NOSQL", "uri": uri, "database": database, "provider": "MONGODB"}
    )

    return BackendDefinition(
        id="test_mongo",
        type=BackendType.NOSQL,
        config=config,
    )


@pytest.fixture()
async def backend(backend_definition, mongo_container):
    """Create, connect, seed, and yield a MongoDBBackend; disconnect on teardown."""
    be = MongoDBBackend(definition=backend_definition)
    await be.connect()

    # Seed the test collection
    db = be._db
    collection = db["users"]
    await collection.delete_many({})
    await collection.insert_many(
        [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35},
        ]
    )

    yield be
    await be.disconnect()


# =============================================================================
# Connection Tests
# =============================================================================


class TestConnection:
    async def test_connect_and_disconnect(self, backend_definition):
        be = MongoDBBackend(definition=backend_definition)
        await be.connect()
        assert be._client is not None
        await be.disconnect()
        assert be._client is None

    async def test_disconnect_when_not_connected(self, backend_definition):
        be = MongoDBBackend(definition=backend_definition)
        await be.disconnect()  # should not raise


# =============================================================================
# Schema Discovery Tests
# =============================================================================


class TestSchemaDiscovery:
    async def test_get_schema(self, backend):
        fields = await backend.get_schema("users")
        assert len(fields) >= 3

        field_map = {f.field_id: f for f in fields}
        assert "name" in field_map
        assert "age" in field_map
        assert field_map["name"].type == FieldType.STRING
        assert field_map["age"].type == FieldType.INTEGER


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent:
    async def test_lookup_by_name(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Alice"),
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 1
        assert result.rows[0]["name"] == "Alice"
        assert result.rows[0]["age"] == 30

    async def test_lookup_with_projections(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Bob"),
            projections=["name"],
        )
        result = await backend.execute("users", intent)
        assert len(result.rows) == 1
        assert result.rows[0]["name"] == "Bob"
        assert "age" not in result.rows[0]

    async def test_lookup_not_found(self, backend):
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="NonExistent"),
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
        assert "_id" not in result.rows[0]

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
            key=IdentityPredicate(field_id="name", value="Alice"),
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
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
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
