"""Integration tests for the pgvector backend.

Uses testcontainers to spin up a real PostgreSQL instance with the pgvector
extension and exercises connect, QUERY with SIMILAR, and inherited RDBMS
capabilities end-to-end.
"""

import unittest
from unittest.mock import patch

from testcontainers.postgres import PostgresContainer

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.semantic import CuratedResource
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    SimilarValue,
)
from backends.vector.pgvector import PgVectorBackend

# =============================================================================
# Module-level fixtures
# =============================================================================

_RESOURCE_ID = "test:documents"

_TABLE_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id        SERIAL PRIMARY KEY,
    title     VARCHAR(200) NOT NULL,
    category  VARCHAR(100) NOT NULL,
    embedding vector(3) NOT NULL
);

INSERT INTO documents (title, category, embedding) VALUES
    ('Introduction to AI',    'tech',    '[0.1, 0.2, 0.3]'),
    ('Advanced ML Techniques', 'tech',    '[0.11, 0.22, 0.33]'),
    ('Cooking 101',            'food',    '[0.9, 0.8, 0.7]'),
    ('Baking Bread',           'food',    '[0.85, 0.75, 0.65]'),
    ('Space Exploration',      'science', '[0.5, 0.5, 0.5]');
"""

_pg_container: PostgresContainer | None = None
_backend_definition: BackendDefinition | None = None


def setUpModule() -> None:
    """Start a PostgreSQL container with pgvector for the test module."""
    global _pg_container, _backend_definition  # noqa: PLW0603
    _pg_container = PostgresContainer("pgvector/pgvector:pg16")
    _pg_container.start()
    url = _pg_container.get_connection_url()
    dsn = url.split("://", 1)[-1]
    dsn = f"postgresql://{dsn}"
    _backend_definition = BackendDefinition(
        id="test_pgvector",
        type=BackendType.VECTOR,
        provider="pgvector",
        config=VectorBackendConfig(
            index_name="documents",
            endpoint=dsn,
            dimensions=3,
        ),
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
    """Return a minimal CuratedResource bound to the documents table."""
    backend_def = _get_backend_definition()
    return CuratedResource.model_validate(
        {
            "resourceId": _RESOURCE_ID,
            "intentClasses": ["*"],
            "backendId": backend_def.id,
            "version": 1,
            "sourceDefinition": {
                "source": "documents",
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
    """Base that creates, seeds, and tears down a PgVectorBackend per test."""

    backend: PgVectorBackend

    async def asyncSetUp(self) -> None:
        self._manifest_patch = patch(
            "backends.rdbms.backend.get_global_manifest_index",
            return_value=_TestManifestIndex(),
        )
        self._manifest_patch.start()
        self.backend = PgVectorBackend(definition=_get_backend_definition())
        await self.backend.connect()
        pool = self.backend._pool
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS documents")
            await conn.execute(_TABLE_DDL)

    async def asyncTearDown(self) -> None:
        await self.backend.disconnect()
        self._manifest_patch.stop()


# =============================================================================
# Connection Tests
# =============================================================================


class TestConnection(unittest.IsolatedAsyncioTestCase):
    async def test_connect_and_disconnect(self) -> None:
        be = PgVectorBackend(definition=_get_backend_definition())
        await be.connect()
        self.assertIsNotNone(be._pool)
        await be.disconnect()
        self.assertIsNone(be._pool)

    async def test_disconnect_when_not_connected(self) -> None:
        be = PgVectorBackend(definition=_get_backend_definition())
        await be.disconnect()  # should not raise


# =============================================================================
# SIMILAR (Vector Similarity) Tests
# =============================================================================


class TestSimilarIntent(_SeededBackendMixin):
    async def test_similar_cosine_top_3(self) -> None:
        """Find 3 documents closest to [0.1, 0.2, 0.3] via cosine distance."""
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2, 0.3], top=3),
                    ),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 3)
        # Closest should be the exact match "Introduction to AI"
        self.assertEqual(result.rows[0]["title"], "Introduction to AI")

    async def test_similar_with_category_filter(self) -> None:
        """SIMILAR with a WHERE filter on category."""
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="category",
                        op=PredicateOperator.EQ,
                        value="tech",
                    ),
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.1, 0.2, 0.3], top=10),
                    ),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        categories = {row["category"] for row in result.rows}
        self.assertEqual(categories, {"tech"})

    async def test_similar_l2_distance(self) -> None:
        """Vector search using L2 distance function."""
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.9, 0.8, 0.7], top=2, distance_function="L2"),
                    ),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.rows[0]["title"], "Cooking 101")

    async def test_similar_with_projections(self) -> None:
        """SIMILAR with explicit projections."""
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="embedding",
                        op=PredicateOperator.SIMILAR,
                        value=SimilarValue(vector=[0.5, 0.5, 0.5], top=1),
                    ),
                ],
            ),
            projections=["title"],
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertIn("title", result.rows[0])
        self.assertNotIn("category", result.rows[0])


# =============================================================================
# Inherited RDBMS Capabilities
# =============================================================================


class TestInheritedRDBMS(_SeededBackendMixin):
    async def test_lookup_by_id(self) -> None:
        intent = LookupIntent(
            resource_id=_RESOURCE_ID,
            key=IdentityPredicate(field_id="id", value=1),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["title"], "Introduction to AI")

    async def test_query_with_filter(self) -> None:
        intent = QueryIntent(
            resource_id=_RESOURCE_ID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(
                        field_id="category",
                        op=PredicateOperator.EQ,
                        value="food",
                    ),
                ],
            ),
        )
        result = await self.backend.execute(intent)
        self.assertEqual(len(result.rows), 2)
        titles = {row["title"] for row in result.rows}
        self.assertEqual(titles, {"Cooking 101", "Baking Bread"})
