# Copyright 2026 Datastrato, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for MongoDB backend."""

import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, NOSQLBackendConfig
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
from backends.nosql.mongodb import MongoDBBackend

# =============================================================================
# Test helpers
# =============================================================================

_RESOURCE_ID = "test-resource"
_SOURCE = "users"


def _make_definition(backend_id: str = "test_mongo") -> BackendDefinition:
    return BackendDefinition(
        id=backend_id,
        type=BackendType.NOSQL,
        provider="mongodb",
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


def _mock_manifest_index() -> MagicMock:
    """Create a mock ManifestIndex that resolves _RESOURCE_ID → _SOURCE."""
    mock_index = MagicMock()
    mock_resource = MagicMock()
    mock_resource.source_definition.source = _SOURCE
    mock_resource.resource_id = _RESOURCE_ID
    mock_index.get_resource.return_value = mock_resource
    return mock_index


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

        docs = await backend._fetch_documents("users", {"name": "Alice"}, {"name": 1}, None, None)

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

        await backend._fetch_documents("users", {}, None, [("age", 1)], 10)

        mock_cursor.sort.assert_called_once_with([("age", 1)])
        mock_cursor.limit.assert_called_once_with(10)


# =============================================================================
# LOOKUP Intent Tests
# =============================================================================


class TestLookupIntent(unittest.IsolatedAsyncioTestCase):
    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_lookup_by_id(self, _mock_idx: MagicMock) -> None:
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
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="_id", value="507f1f77bcf86cd799439011"),
        )
        result = await backend.execute(intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")

    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_lookup_with_projections(self, _mock_idx: MagicMock) -> None:
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
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="name", value="Alice"),
            projections=["name"],
        )
        result = await backend.execute(intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")


# =============================================================================
# QUERY Intent Tests
# =============================================================================


class TestQueryIntent(unittest.IsolatedAsyncioTestCase):
    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_query_with_filter(self, _mock_idx: MagicMock) -> None:
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
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        result = await backend.execute(intent)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")

    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_query_with_order_and_limit(self, _mock_idx: MagicMock) -> None:
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
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
            order_by=[SortOrder(field_id="age", direction="ASC")],
            limit=10,
        )
        await backend.execute(intent)

        mock_cursor.sort.assert_called_once()
        mock_cursor.limit.assert_called_once_with(10)

    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_query_in_operator(self, _mock_idx: MagicMock) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.IN, value=["Alice", "Bob"]),
                ],
            ),
        )
        await backend.execute(intent)

        # Verify find was called with correct filter
        call_args = mock_coll.find.call_args
        self.assertIn("name", call_args[0][0])
        self.assertIn("$in", call_args[0][0]["name"])

    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_query_contains_operator(self, _mock_idx: MagicMock) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        mock_coll = _make_mock_collection()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_coll.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_coll

        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="li"),
                ],
            ),
        )
        await backend.execute(intent)

        # Verify find was called with regex
        call_args = mock_coll.find.call_args
        self.assertIn("name", call_args[0][0])
        self.assertIn("$regex", call_args[0][0]["name"])


# =============================================================================
# Unsupported Intent Tests
# =============================================================================


class TestUnsupportedIntents(unittest.IsolatedAsyncioTestCase):
    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_ingest_not_supported(self, _mock_idx: MagicMock) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

        intent = IngestIntent(resource_id=_RESOURCE_ID, payload=[{"name": "Dave", "age": 40}])
        with self.assertRaisesRegex(NotImplementedError, "INGEST"):
            await backend.execute(intent)

    @patch("backends.nosql.mongodb.get_global_manifest_index", return_value=_mock_manifest_index())
    async def test_revise_not_supported(self, _mock_idx: MagicMock) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        backend._db = MagicMock()

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
            await backend.execute(intent)


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

    def test_normalize_document_objectid_in_list(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        oid = ObjectId("507f1f77bcf86cd799439011")
        doc = {"refs": [oid, "plain", 42]}

        normalized = backend._normalize_document(doc)

        self.assertEqual(normalized["refs"][0], "507f1f77bcf86cd799439011")
        self.assertEqual(normalized["refs"][1], "plain")
        self.assertEqual(normalized["refs"][2], 42)

    def test_normalize_filter_id_with_eq_operator(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        filt = {"_id": {"$eq": "507f1f77bcf86cd799439011"}}
        result = backend._normalize_filter(filt)
        self.assertIsInstance(result["_id"]["$eq"], ObjectId)

    def test_normalize_filter_id_with_in_operator(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        filt = {"_id": {"$in": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"]}}
        result = backend._normalize_filter(filt)
        for v in result["_id"]["$in"]:
            self.assertIsInstance(v, ObjectId)

    def test_normalize_filter_id_direct_string(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        filt = {"_id": "507f1f77bcf86cd799439011"}
        result = backend._normalize_filter(filt)
        self.assertIsInstance(result["_id"], ObjectId)

    def test_normalize_filter_non_id_field_unchanged(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        filt = {"name": "Alice"}
        result = backend._normalize_filter(filt)
        self.assertEqual(result["name"], "Alice")


# =============================================================================
# Regex Safety Tests
# =============================================================================


class TestRegexSafety(unittest.TestCase):
    def test_contains_escapes_metacharacters(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        pred = Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="1+1=2")
        result = backend._translate_predicate(pred)
        pattern = result["name"]["$regex"]
        # The pattern should not interpret + as a regex quantifier
        self.assertNotEqual(pattern, "1+1=2")
        self.assertIn(r"\+", pattern)
        # Should match the literal string
        self.assertIsNotNone(re.search(pattern, "1+1=2"))
        # Should NOT match "112" (which unescaped + would match)
        self.assertIsNone(re.search(pattern, "112"))

    def test_like_anchored_exact_match(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        pred = Predicate(field_id="name", op=PredicateOperator.LIKE, value="Alice")
        result = backend._translate_predicate(pred)
        pattern = result["name"]["$regex"]
        self.assertTrue(pattern.startswith("^"))
        self.assertTrue(pattern.endswith("$"))
        self.assertIsNotNone(re.match(pattern, "Alice"))
        self.assertIsNone(re.match(pattern, "Alice Smith"))

    def test_like_wildcards(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        pred = Predicate(field_id="name", op=PredicateOperator.LIKE, value="%Alice%")
        result = backend._translate_predicate(pred)
        pattern = result["name"]["$regex"]
        self.assertIsNotNone(re.match(pattern, "xAlicex"))
        self.assertIsNotNone(re.match(pattern, "Alice"))

    def test_like_escapes_regex_metacharacters(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        pred = Predicate(field_id="name", op=PredicateOperator.LIKE, value="a.b")
        result = backend._translate_predicate(pred)
        pattern = result["name"]["$regex"]
        self.assertIsNotNone(re.match(pattern, "a.b"))
        self.assertIsNone(re.match(pattern, "axb"))

    def test_ilike_case_insensitive(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        pred = Predicate(field_id="name", op=PredicateOperator.ILIKE, value="%alice%")
        result = backend._translate_predicate(pred)
        self.assertEqual(result["name"]["$options"], "i")


# =============================================================================
# Limit=0 Test
# =============================================================================


class TestLimitZero(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_documents_limit_zero_returns_empty(self) -> None:
        backend = MongoDBBackend(definition=_make_definition())
        mock_db = MagicMock()
        backend._db = mock_db

        result = await backend._fetch_documents("users", {}, None, None, 0)
        self.assertEqual(result, [])
        # find() should not even be called
        mock_db.__getitem__.return_value.find.assert_not_called()
