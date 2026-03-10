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

"""Unit tests for the Vector backend modules."""

import unittest
from typing import Any

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    VectorBackendConfig,
)
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    Intent,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    SimilarValue,
    SortOrder,
)
from backends.base import BackendResult
from backends.vector.backend import VectorBackend
from backends.vector.pgvector import PgVectorBackend, _inject_password

# =============================================================================
# Helpers
# =============================================================================


_RESOURCE_ID = "test:documents"


def _make_definition() -> BackendDefinition:
    return BackendDefinition(
        id="test_vector",
        type=BackendType.VECTOR,
        provider="pgvector",
        config=VectorBackendConfig(
            index_name="documents",
            endpoint="postgresql://user@localhost/db",
            dimensions=1536,
        ),
    )


class _StubVectorBackend(VectorBackend):
    """Concrete stub for protocol-level helper tests (no SQL)."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def execute(self, intent: Intent) -> BackendResult:
        return BackendResult(rows=[])


class _StubPgVectorBackend(PgVectorBackend):
    """Concrete stub that satisfies abstract methods without a real DB."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def fetch_all(self, sql: str, params: list[Any], source: str) -> list[dict[str, Any]]:
        return []


def _make_vector_backend() -> _StubVectorBackend:
    return _StubVectorBackend(definition=_make_definition())


def _make_pgvector_backend() -> _StubPgVectorBackend:
    return _StubPgVectorBackend(definition=_make_definition())


# =============================================================================
# SQL Generation — SIMILAR predicate
# =============================================================================


class TestSimilarSQLGeneration(unittest.TestCase):
    """Test that SIMILAR predicates produce the correct SQL."""

    def setUp(self) -> None:
        self.backend = _make_pgvector_backend()

    def test_similar_cosine_distance_default(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2, 0.3], top=5),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn('ORDER BY "embedding" <=>', sql)
        self.assertIn("::vector", sql)
        self.assertIn("LIMIT 5", sql)
        self.assertEqual(params, ["[0.1,0.2,0.3]"])

    def test_similar_l2_distance(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[1.0, 2.0], top=3, distance_function="L2"),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn("<->", sql)
        self.assertIn("LIMIT 3", sql)
        self.assertEqual(params, ["[1.0,2.0]"])

    def test_similar_inner_product_distance(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(
                            vector=[1.0, 2.0], top=3, distance_function="INNER_PRODUCT"
                        ),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn("<#>", sql)

    def test_similar_with_threshold(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=10, threshold=0.5),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn("< (1.0 - $2)", sql)
        self.assertEqual(params[1], 0.5)

    def test_similar_threshold_l2(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(
                            vector=[0.1, 0.2], top=10, threshold=0.5, distance_function="L2"
                        ),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn("< $2", sql)
        self.assertNotIn("1.0 -", sql)
        self.assertEqual(params[1], 0.5)

    def test_similar_threshold_inner_product(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(
                            vector=[0.1, 0.2],
                            top=10,
                            threshold=0.5,
                            distance_function="INNER_PRODUCT",
                        ),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn("< (-$2)", sql)
        self.assertEqual(params[1], 0.5)

    def test_similar_with_other_predicates(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="category",
                        op=PredicateOperator.EQ,
                        value="sports",
                    ),
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=5),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn('WHERE "category" = $1', sql)
        self.assertIn('ORDER BY "embedding" <=>', sql)
        self.assertEqual(params[0], "sports")
        self.assertEqual(params[1], "[0.1,0.2]")

    def test_similar_top_overrides_intent_limit(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=5),
                    ),
                ],
            ),
            limit=100,
        )
        sql, _ = self.backend._build_query_sql("documents", intent)
        self.assertIn("LIMIT 5", sql)
        self.assertNotIn("LIMIT 100", sql)

    def test_similar_falls_back_to_intent_limit(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2]),
                    ),
                ],
            ),
            limit=20,
        )
        sql, _ = self.backend._build_query_sql("documents", intent)
        self.assertIn("LIMIT 20", sql)

    def test_similar_with_projections(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1], top=5),
                    ),
                ],
            ),
            projections=["id", "title"],
        )
        sql, _ = self.backend._build_query_sql("documents", intent)
        self.assertTrue(sql.startswith('SELECT "id", "title" FROM'))

    def test_invalid_similar_value_type(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value="not_a_similar_value",
                    ),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "SimilarValue"):
            self.backend._build_query_sql("documents", intent)

    def test_similar_value_without_vector(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(blob="base64data"),
                    ),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "vector must be set"):
            self.backend._build_query_sql("documents", intent)

    def test_unsupported_distance_function(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported distance function"):
            self.backend.distance_operator("HAMMING")

    def test_similar_in_or_group_raises(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="OR",
                predicates=[
                    Predicate(field_id="category", op=PredicateOperator.EQ, value="tech"),
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=5),
                    ),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "not supported inside OR groups"):
            self.backend._build_query_sql("documents", intent)

    def test_nested_similar_raises(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="category", op=PredicateOperator.EQ, value="tech"),
                    PredicateGroup(
                        op="AND",
                        predicates=[
                            Predicate(
                                field_id="embedding",
                                op=PredicateOperator.SIMILAR,
                                value=SimilarValue(vector=[0.1, 0.2], top=5),
                            ),
                        ],
                    ),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "top level"):
            self.backend._build_query_sql("documents", intent)

    def test_multiple_similar_predicates(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="text_embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=5),
                    ),
                    Predicate(
                        field_id="image_embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.3, 0.4], top=5),
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("documents", intent)
        self.assertIn('ORDER BY "text_embedding" <=>', sql)
        self.assertIn('"image_embedding" <=>', sql)
        self.assertEqual(params, ["[0.1,0.2]", "[0.3,0.4]"])
        self.assertIn("LIMIT 5", sql)

    def test_multiple_similar_conflicting_top_raises(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="text_embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1], top=5),
                    ),
                    Predicate(
                        field_id="image_embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.2], top=10),
                    ),
                ],
            ),
        )
        with self.assertRaisesRegex(ValueError, "conflicting top values"):
            self.backend._build_query_sql("documents", intent)

    def test_similar_with_order_by_secondary_sort(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2], top=5),
                    ),
                ],
            ),
            order_by=[SortOrder(field_id="title", direction="ASC")],
        )
        sql, _ = self.backend._build_query_sql("documents", intent)
        self.assertIn('ORDER BY "embedding" <=>', sql)
        self.assertIn('"title" ASC', sql)
        order_idx = sql.index("ORDER BY")
        distance_idx = sql.index("<=>", order_idx)
        title_idx = sql.index('"title" ASC', order_idx)
        self.assertLess(distance_idx, title_idx)


# =============================================================================
# SQL Generation — inherited RDBMS capabilities
# =============================================================================


class TestInheritedRDBMSCapabilities(unittest.TestCase):
    """Verify PgVectorBackend retains standard RDBMS query capabilities."""

    def setUp(self) -> None:
        self.backend = _make_pgvector_backend()

    def test_query_without_similar(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GT, value=25),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertIn('"age" > $1', sql)
        self.assertNotIn("<=>", sql)
        self.assertEqual(params, [25])

    def test_lookup_intent(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="id", value=1),
        )
        sql, params = self.backend._build_lookup_sql("users", intent)
        self.assertIn('"id" = $1', sql)
        self.assertEqual(params, [1])


# =============================================================================
# Distance operator hook
# =============================================================================


class TestDistanceOperator(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _make_pgvector_backend()

    def test_cosine(self) -> None:
        self.assertEqual(self.backend.distance_operator("COSINE"), "<=>")

    def test_l2(self) -> None:
        self.assertEqual(self.backend.distance_operator("L2"), "<->")

    def test_inner_product(self) -> None:
        self.assertEqual(self.backend.distance_operator("INNER_PRODUCT"), "<#>")

    def test_none_defaults_to_cosine(self) -> None:
        self.assertEqual(self.backend.distance_operator(None), "<=>")

    def test_case_insensitive(self) -> None:
        self.assertEqual(self.backend.distance_operator("cosine"), "<=>")


# =============================================================================
# Extract similar helper
# =============================================================================


class TestExtractSimilar(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _make_vector_backend()

    def test_extracts_similar_predicate(self) -> None:
        similar = Predicate(
            field_id="embedding",
            op=PredicateOperator.SIMILAR,
            value=SimilarValue(vector=[0.1]),
        )
        other = Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice")
        group = PredicateGroup(op="AND", predicates=[other, similar])

        extracted, remaining = self.backend._extract_similar(group)
        self.assertEqual(len(extracted), 1)
        self.assertIs(extracted[0], similar)
        self.assertEqual(len(remaining.predicates), 1)
        self.assertIs(remaining.predicates[0], other)

    def test_no_similar_returns_empty_list(self) -> None:
        other = Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice")
        group = PredicateGroup(op="AND", predicates=[other])

        extracted, remaining = self.backend._extract_similar(group)
        self.assertEqual(extracted, [])
        self.assertEqual(len(remaining.predicates), 1)

    def test_extracts_multiple_similar_predicates(self) -> None:
        sim1 = Predicate(
            field_id="text_embedding",
            op=PredicateOperator.SIMILAR,
            value=SimilarValue(vector=[0.1]),
        )
        sim2 = Predicate(
            field_id="image_embedding",
            op=PredicateOperator.SIMILAR,
            value=SimilarValue(vector=[0.2]),
        )
        other = Predicate(field_id="name", op=PredicateOperator.EQ, value="Alice")
        group = PredicateGroup(op="AND", predicates=[sim1, other, sim2])

        extracted, remaining = self.backend._extract_similar(group)
        self.assertEqual(len(extracted), 2)
        self.assertIs(extracted[0], sim1)
        self.assertIs(extracted[1], sim2)
        self.assertEqual(len(remaining.predicates), 1)


# =============================================================================
# PgVectorBackend — password injection
# =============================================================================


class TestPgVectorInjectPassword(unittest.TestCase):
    def test_simple_dsn_without_password(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "secret")
        self.assertEqual(result, "postgresql://user:secret@localhost/db")

    def test_dsn_with_existing_password(self) -> None:
        result = _inject_password("postgresql://user:old@localhost/db", "new")
        self.assertEqual(result, "postgresql://user:new@localhost/db")

    def test_dsn_without_host_returns_unchanged(self) -> None:
        result = _inject_password("not-a-url", "secret")
        self.assertEqual(result, "not-a-url")

    def test_dsn_without_username_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a username"):
            _inject_password("postgresql://localhost/db", "secret")


# =============================================================================
# PgVectorBackend — connection
# =============================================================================


class TestPgVectorConnection(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_all_without_connect_raises(self) -> None:
        be = PgVectorBackend(definition=_make_definition())
        with self.assertRaisesRegex(ConnectionError, "not connected"):
            await be.fetch_all("SELECT 1", [], "test")

    async def test_disconnect_when_not_connected(self) -> None:
        be = PgVectorBackend(definition=_make_definition())
        await be.disconnect()  # should not raise


# =============================================================================
# Server backend factory — VECTOR type
# =============================================================================


class TestCreateBackendVector(unittest.TestCase):
    def test_create_backend_vector_returns_pgvector(self) -> None:
        from adp_hypervisor.server import _create_backend

        definition = _make_definition()
        backend = _create_backend(definition)
        self.assertIsInstance(backend, PgVectorBackend)
