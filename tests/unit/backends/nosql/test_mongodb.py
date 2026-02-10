"""Tests for MongoDB backend."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, NOSQLBackendConfig
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
# Test helpers
# =============================================================================


def _make_definition(backend_id: str = "test_mongo") -> BackendDefinition:
    return BackendDefinition(
        id=backend_id,
        type=BackendType.NOSQL,
        config=NOSQLBackendConfig(type="NOSQL"),
    )


def _make_mock_collection() -> MagicMock:
    """Create a mock MongoDB collection."""
    mock_coll = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_coll.find.return_value = mock_cursor
    mock_coll.aggregate.return_value = mock_cursor
    return mock_coll


# =============================================================================
# Initialization Tests
# =============================================================================


class TestMongoDBBackendInit(unittest.TestCase):
    def test_backend_id(self) -> None:
        backend = MongoDBBackend(definition=_make_definition("mongo1"))
        self.assertEqual(backend.backend_id, "mongo1")

    def test_initial_state(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        self.assertIsNone(backend._client)
        self.assertIsNone(backend._db)

    def test_definition_property(self) -> None:
        defn = _make_definition("mongo_test")
        backend = MongoDBBackend(definition=defn)
        self.assertIs(backend.definition, defn)
        self.assertEqual(backend.definition.type, BackendType.NOSQL)


# =============================================================================
# Connection Tests
# =============================================================================


class TestMongoDBBackendConnection(unittest.IsolatedAsyncioTestCase):
    @patch("motor.motor_asyncio.AsyncIOMotorClient")
    async def test_connect(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_admin = MagicMock()
        mock_admin.command = AsyncMock(return_value={"ok": 1})
        mock_client.admin = mock_admin
        mock_client_class.return_value = mock_client

        backend = MongoDBBackend(definition=_make_definition())
        await backend.connect()

        self.assertIsNotNone(backend._client)
        self.assertIsNotNone(backend._db)
        mock_admin.command.assert_called_once_with("ping")

    async def test_disconnect(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_client = MagicMock()
        backend._client = mock_client
        backend._db = MagicMock()

        await backend.disconnect()

        self.assertIsNone(backend._client)
        self.assertIsNone(backend._db)
        mock_client.close.assert_called_once()

    async def test_disconnect_when_not_connected(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        await backend.disconnect()  # should not raise


# =============================================================================
# Schema Discovery Tests
# =============================================================================


class TestSchemaDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_get_schema(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        # Mock collection with sample documents
        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(), "name": "Alice", "age": 30, "active": True},
                {"_id": ObjectId(), "name": "Bob", "age": 25, "active": False},
            ]
        )
        mock_coll.aggregate.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        fields = await backend.get_schema("users")

        self.assertEqual(len(fields), 4)
        field_map = {f.field_id: f for f in fields}
        self.assertIn("_id", field_map)
        self.assertIn("name", field_map)
        self.assertIn("age", field_map)
        self.assertIn("active", field_map)
        self.assertEqual(field_map["name"].type, FieldType.STRING)
        self.assertEqual(field_map["age"].type, FieldType.INTEGER)
        self.assertEqual(field_map["active"].type, FieldType.BOOLEAN)

    async def test_get_schema_empty_collection(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.aggregate.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        fields = await backend.get_schema("empty")

        self.assertEqual(len(fields), 0)


# =============================================================================
# Query Execution Tests
# =============================================================================


class TestQueryExecution(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_documents(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId("507f1f77bcf86cd799439011"), "name": "Alice"},
            ]
        )
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        docs = await backend.fetch_documents("users", {"name": "Alice"}, {"name": 1}, None, None)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Alice")
        self.assertIsInstance(docs[0]["_id"], str)

    async def test_fetch_documents_with_sort_and_limit(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        await backend.fetch_documents("users", {}, None, [("age", 1)], 10)

        mock_cursor.sort.assert_called_once_with([("age", 1)])
        mock_cursor.limit.assert_called_once_with(10)


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_by_id(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId("507f1f77bcf86cd799439011"), "name": "Alice"},
            ]
        )
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = LookupIntent(
            key=IdentityPredicate(field_id="_id", value="507f1f77bcf86cd799439011"),
        )
        result = await backend.execute("users", intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")

    async def test_lookup_with_projections(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"name": "Alice"},
            ]
        )
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = LookupIntent(
            key=IdentityPredicate(field_id="name", value="Alice"),
            projections=["name"],
        )
        result = await backend.execute("users", intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")


# =============================================================================
# QUERY Intent Tests
# =============================================================================


class TestQueryIntent(unittest.IsolatedAsyncioTestCase):
    async def test_query_with_filter(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(), "name": "Alice", "age": 30},
            ]
        )
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        result = await backend.execute("users", intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")

    async def test_query_with_order_and_limit(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
            order_by=[SortOrder(field_id="age", direction="ASC")],
            limit=10,
        )
        await backend.execute("users", intent)

        mock_cursor.sort.assert_called_once()
        mock_cursor.limit.assert_called_once_with(10)

    async def test_query_in_operator(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=["Alice", "Bob"]),
                ],
            ),
        )
        await backend.execute("users", intent)

        # Verify find was called with correct filter
        call_args = mock_coll.find.call_args
        self.assertIn("name", call_args[0][0])
        self.assertIn("$in", call_args[0][0]["name"])

    async def test_query_contains_operator(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="li"),
                ],
            ),
        )
        await backend.execute("users", intent)

        # Verify find was called with regex
        call_args = mock_coll.find.call_args
        self.assertIn("name", call_args[0][0])
        self.assertIn("$regex", call_args[0][0]["name"])


# =============================================================================
# Validate Tests
# =============================================================================


class TestValidate(unittest.IsolatedAsyncioTestCase):
    async def test_validate_valid_lookup(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = LookupIntent(
            key=IdentityPredicate(field_id="id", value=1),
        )
        issues = await backend.validate("users", intent)

        self.assertEqual(issues, [])

    async def test_validate_valid_query(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=20),
                ],
            ),
        )
        issues = await backend.validate("users", intent)

        self.assertEqual(issues, [])

    async def test_validate_invalid_in_operator(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = QueryIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=[]),
                ],
            ),
        )
        issues = await backend.validate("users", intent)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "BLOCKING")


# =============================================================================
# Unsupported Intent Tests
# =============================================================================


class TestUnsupportedIntents(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_not_supported(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        with self.assertRaisesRegex(NotImplementedError, "INGEST"):
            await backend.execute("users", intent)

    async def test_revise_not_supported(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = ReviseIntent(
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="id", op=PredicateOperator.EQ, value=1),
                ],
            ),
            payload={"name": "Updated"},
        )
        with self.assertRaisesRegex(NotImplementedError, "REVISE"):
            await backend.execute("users", intent)

    async def test_validate_ingest_returns_issue(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = IngestIntent(payload=[{"name": "Dave", "age": 40}])
        issues = await backend.validate("users", intent)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "BLOCKING")


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods(unittest.TestCase):
    def test_normalize_document_with_objectid(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        doc = {"_id": ObjectId("507f1f77bcf86cd799439011"), "name": "Alice"}

        normalized = backend._normalize_document(doc)

        self.assertEqual(normalized["_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(normalized["name"], "Alice")

    def test_normalize_document_nested(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "profile": {"_id": ObjectId("507f1f77bcf86cd799439012"), "bio": "test"},
        }

        normalized = backend._normalize_document(doc)

        self.assertEqual(normalized["_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(normalized["profile"]["_id"], "507f1f77bcf86cd799439012")

    def test_infer_field_type(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())

        self.assertEqual(backend._infer_field_type({"str"}), FieldType.STRING)
        self.assertEqual(backend._infer_field_type({"int"}), FieldType.INTEGER)
        self.assertEqual(backend._infer_field_type({"float"}), FieldType.FLOAT)
        self.assertEqual(backend._infer_field_type({"bool"}), FieldType.BOOLEAN)
        self.assertEqual(backend._infer_field_type({"list"}), FieldType.JSON)
        self.assertEqual(backend._infer_field_type({"dict"}), FieldType.JSON)
        self.assertEqual(backend._infer_field_type({"ObjectId"}), FieldType.STRING)
