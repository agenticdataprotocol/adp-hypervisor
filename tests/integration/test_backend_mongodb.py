"""Integration tests for the MongoDB backend.

Uses testcontainers to spin up a real MongoDB instance and exercises
connect, LOOKUP, and QUERY intents end-to-end.
"""

import unittest

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
# Module-level container and backend definition
# =============================================================================

_mongo_container = None
_backend_definition = None


def setUpModule() -> None:
    """Set up MongoDB container for all tests in this module."""
    global _mongo_container, _backend_definition
    _mongo_container = MongoDbContainer("mongo:7")
    _mongo_container.start()

    connection_url = _mongo_container.get_connection_url()

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

    _backend_definition = BackendDefinition(
        id="test_mongo",
        type=BackendType.NOSQL,
        config=config,
    )


def tearDownModule() -> None:
    """Tear down MongoDB container after all tests."""
    global _mongo_container
    if _mongo_container is not None:
        _mongo_container.stop()


# =============================================================================
# Connection Tests
# =============================================================================


class TestConnection(unittest.IsolatedAsyncioTestCase):
    async def test_connect_and_disconnect(self) -> None:
        be = MongoDBBackend(definition=_backend_definition)
        await be.connect()
        self.assertIsNotNone(be._client)
        await be.disconnect()
        self.assertIsNone(be._client)

    async def test_disconnect_when_not_connected(self) -> None:
        be = MongoDBBackend(definition=_backend_definition)
        await be.disconnect()  # should not raise


# =============================================================================
# Schema Discovery Tests
# =============================================================================


class TestSchemaDiscovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up backend and seed data for each test."""
        self.backend = MongoDBBackend(definition=_backend_definition)
        await self.backend.connect()

        # Seed the test collection
        db = self.backend._db
        collection = db["users"]
        await collection.delete_many({})
        await collection.insert_many(
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
                {"name": "Charlie", "age": 35},
            ]
        )

    async def asyncTearDown(self) -> None:
        """Disconnect backend after each test."""
        await self.backend.disconnect()

    async def test_get_schema(self) -> None:
        fields = await self.backend.get_schema("users")
        self.assertGreaterEqual(len(fields), 3)

        field_map = {f.field_id: f for f in fields}
        self.assertIn("name", field_map)
        self.assertIn("age", field_map)
        self.assertEqual(field_map["name"].type, FieldType.STRING)
        self.assertEqual(field_map["age"].type, FieldType.INTEGER)


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up backend and seed data for each test."""
        self.backend = MongoDBBackend(definition=_backend_definition)
        await self.backend.connect()

        # Seed the test collection
        db = self.backend._db
        collection = db["users"]
        await collection.delete_many({})
        await collection.insert_many(
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
                {"name": "Charlie", "age": 35},
            ]
        )

    async def asyncTearDown(self) -> None:
        """Disconnect backend after each test."""
        await self.backend.disconnect()

    async def test_lookup_by_name(self) -> None:
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Alice"),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")
        self.assertEqual(result.rows[0]["age"], 30)

    async def test_lookup_with_projections(self) -> None:
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Bob"),
            projections=["name"],
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Bob")
        self.assertNotIn("age", result.rows[0])

    async def test_lookup_not_found(self) -> None:
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="NonExistent"),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 0)


# =============================================================================
# QUERY Intent Tests
# =============================================================================


class TestQueryIntent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up backend and seed data for each test."""
        self.backend = MongoDBBackend(definition=_backend_definition)
        await self.backend.connect()

        # Seed the test collection
        db = self.backend._db
        collection = db["users"]
        await collection.delete_many({})
        await collection.insert_many(
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
                {"name": "Charlie", "age": 35},
            ]
        )

    async def asyncTearDown(self) -> None:
        """Disconnect backend after each test."""
        await self.backend.disconnect()

    async def test_query_all(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 3)

    async def test_query_with_filter(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_with_order_and_limit(self) -> None:
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
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.rows[0]["name"], "Bob")
        self.assertEqual(result.rows[1]["name"], "Alice")

    async def test_query_with_projections(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
            projections=["name", "age"],
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Charlie")
        self.assertEqual(result.rows[0]["age"], 35)
        self.assertNotIn("_id", result.rows[0])

    async def test_query_in_operator(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=["Alice", "Bob"]),
                ],
            ),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)

    async def test_query_in_empty_list_raises(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=[]),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            await self.backend.execute("users", intent)

    async def test_query_contains_substring(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="li"),
                ],
            ),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_or_predicates(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="OR",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Charlie"),
                ],
            ),
        )
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Charlie"})

    async def test_query_nested_predicates(self) -> None:
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
        result = await self.backend.execute("users", intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Bob"})


# =============================================================================
# Validate Tests
# =============================================================================


class TestValidate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up backend for each test."""
        self.backend = MongoDBBackend(definition=_backend_definition)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Disconnect backend after each test."""
        await self.backend.disconnect()

    async def test_validate_valid_lookup(self) -> None:
        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Alice"),
        )
        issues = await self.backend.validate("users", intent)
        self.assertEqual(issues, [])

    async def test_validate_valid_query(self) -> None:
        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=20),
                ],
            ),
        )
        issues = await self.backend.validate("users", intent)
        self.assertEqual(issues, [])


# =============================================================================
# Unsupported Intent Tests
# =============================================================================


class TestUnsupportedIntents(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up backend for each test."""
        self.backend = MongoDBBackend(definition=_backend_definition)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Disconnect backend after each test."""
        await self.backend.disconnect()

    async def test_ingest_not_supported(self) -> None:
        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        with self.assertRaisesRegex(NotImplementedError, "INGEST"):
            await self.backend.execute("users", intent)

    async def test_revise_not_supported(self) -> None:
        intent = ReviseIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                ],
            ),
            payload={"name": "Updated"},
        )
        with self.assertRaisesRegex(NotImplementedError, "REVISE"):
            await self.backend.execute("users", intent)

    async def test_validate_ingest_returns_issue(self) -> None:
        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        issues = await self.backend.validate("users", intent)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "BLOCKING")
