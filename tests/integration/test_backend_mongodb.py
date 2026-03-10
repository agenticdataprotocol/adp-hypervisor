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

"""Integration tests for the MongoDB backend.

Uses testcontainers to spin up a real MongoDB instance and exercises
connect, LOOKUP, and QUERY intents end-to-end.
"""

import unittest
from unittest.mock import MagicMock, patch

from testcontainers.mongodb import MongoDbContainer

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    NOSQLBackendConfig,
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
from backends.nosql.mongodb import MongoDBBackend

# =============================================================================
# Module-level container and backend definition
# =============================================================================

_mongo_container = None
_backend_definition = None

_RESOURCE_ID = "integration-test-resource"
_SOURCE = "users"


def _mock_manifest_index() -> MagicMock:
    """Create a mock ManifestIndex that resolves _RESOURCE_ID → _SOURCE."""
    mock_index = MagicMock()
    mock_resource = MagicMock()
    mock_resource.source_definition.source = _SOURCE
    mock_resource.resource_id = _RESOURCE_ID
    mock_index.get_resource.return_value = mock_resource
    return mock_index


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
    config = NOSQLBackendConfig.model_validate({"type": "NOSQL", "uri": uri, "database": database})

    _backend_definition = BackendDefinition(
        id="test_mongo",
        type=BackendType.NOSQL,
        provider="MONGODB",
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
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="name", value="Alice"),
        )
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
            result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Alice")
        self.assertEqual(result.rows[0]["age"], 30)

    async def test_lookup_with_projections(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="name", value="Bob"),
            projections=["name"],
        )
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
            result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Bob")
        self.assertNotIn("age", result.rows[0])

    async def test_lookup_not_found(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="name", value="NonExistent"),
        )
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
            result = await self.backend.execute(intent)
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
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=0),
                ],
            ),
        )
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
            result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "Charlie")
        self.assertEqual(result.rows[0]["age"], 35)
        self.assertNotIn("_id", result.rows[0])

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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
            with patch(
                "backends.nosql.mongodb.get_global_manifest_index",
                return_value=_mock_manifest_index(),
            ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
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
        with patch(
            "backends.nosql.mongodb.get_global_manifest_index",
            return_value=_mock_manifest_index(),
        ):
            result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"Alice", "Bob"})


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
        intent = IngestIntent(resource_id=_RESOURCE_ID, payload=[{"name": "Dave", "age": 40}])
        with self.assertRaisesRegex(NotImplementedError, "INGEST"):
            with patch(
                "backends.nosql.mongodb.get_global_manifest_index",
                return_value=_mock_manifest_index(),
            ):
                await self.backend.execute(intent)

    async def test_revise_not_supported(self) -> None:
        intent = ReviseIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice"),
                ],
            ),
            payload={"name": "Updated"},
        )
        with self.assertRaisesRegex(NotImplementedError, "REVISE"):
            with patch(
                "backends.nosql.mongodb.get_global_manifest_index",
                return_value=_mock_manifest_index(),
            ):
                await self.backend.execute(intent)
