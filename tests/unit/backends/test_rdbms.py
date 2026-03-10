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

"""Unit tests for the RDBMS backend modules."""

import unittest
from typing import Any

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, RDBMSBackendConfig
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
from backends.rdbms.backend import RDBMSBackend
from backends.rdbms.postgres import _inject_password

# =============================================================================
# Test helpers
# =============================================================================


_RID = "com.acme:test"  # dummy resource_id for all intent constructors in this file


def _make_definition() -> BackendDefinition:
    return BackendDefinition(
        id="test_rdbms",
        type=BackendType.RDBMS,
        provider="postgresql",
        config=RDBMSBackendConfig(uri="postgresql://localhost/test"),
    )


class _StubRDBMSBackend(RDBMSBackend):
    """Minimal concrete subclass for testing SQL translation."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def fetch_all(self, sql: str, params: list[Any], source: str) -> list[dict[str, Any]]:
        return []


# =============================================================================
# Hook Method Tests
# =============================================================================


class TestHookMethods(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _StubRDBMSBackend(definition=_make_definition())

    def test_quote_identifier(self) -> None:
        self.assertEqual(self.backend.quote_identifier("name"), '"name"')

    def test_quote_identifier_with_double_quote(self) -> None:
        self.assertEqual(self.backend.quote_identifier('col"x'), '"col""x"')

    def test_placeholder(self) -> None:
        self.assertEqual(self.backend.placeholder(1), "$1")
        self.assertEqual(self.backend.placeholder(5), "$5")

    def test_build_limit_clause(self) -> None:
        self.assertEqual(self.backend.build_limit_clause(10), "LIMIT 10")


# =============================================================================
# Lookup SQL Tests
# =============================================================================


class TestBuildLookupSQL(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _StubRDBMSBackend(definition=_make_definition())

    def test_basic_lookup(self) -> None:
        intent = LookupIntent(resource_id=_RID, key=IdentityPredicate(field_id="id", value=42))
        sql, params = self.backend._build_lookup_sql("users", intent)
        self.assertEqual(sql, 'SELECT * FROM "users" WHERE "id" = $1')
        self.assertEqual(params, [42])

    def test_lookup_with_projections(self) -> None:
        intent = LookupIntent(
            resource_id=_RID,
            key=IdentityPredicate(field_id="id", value=1),
            projections=["name", "age"],
        )
        sql, params = self.backend._build_lookup_sql("users", intent)
        self.assertEqual(sql, 'SELECT "name", "age" FROM "users" WHERE "id" = $1')
        self.assertEqual(params, [1])


# =============================================================================
# Query SQL Tests
# =============================================================================


class TestBuildQuerySQL(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _StubRDBMSBackend(definition=_make_definition())

    def test_single_eq_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="status", op=PredicateOperator.EQ, value="active")],
            ),
        )
        sql, params = self.backend._build_query_sql("orders", intent)
        self.assertEqual(sql, 'SELECT * FROM "orders" WHERE "status" = $1')
        self.assertEqual(params, ["active"])

    def test_gt_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="age", op=PredicateOperator.GT, value=18)],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(sql, 'SELECT * FROM "users" WHERE "age" > $1')
        self.assertEqual(params, [18])

    def test_multiple_predicates_and(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="age", op=PredicateOperator.GTE, value=18),
                    Predicate(field_id="age", op=PredicateOperator.LTE, value=65),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(sql, 'SELECT * FROM "users" WHERE "age" >= $1 AND "age" <= $2')
        self.assertEqual(params, [18, 65])

    def test_neq_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="status", op=PredicateOperator.NEQ, value="deleted")
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("items", intent)
        self.assertEqual(sql, 'SELECT * FROM "items" WHERE "status" != $1')
        self.assertEqual(params, ["deleted"])

    def test_lt_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="score", op=PredicateOperator.LT, value=50)],
            ),
        )
        sql, params = self.backend._build_query_sql("results", intent)
        self.assertEqual(sql, 'SELECT * FROM "results" WHERE "score" < $1')
        self.assertEqual(params, [50])

    def test_contains_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="name", op=PredicateOperator.CONTAINS, value="john"),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(sql, 'SELECT * FROM "users" WHERE "name" LIKE $1')
        self.assertEqual(params, ["%john%"])

    def test_like_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="email", op=PredicateOperator.LIKE, value="%@gmail.com"),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(sql, 'SELECT * FROM "users" WHERE "email" LIKE $1')
        self.assertEqual(params, ["%@gmail.com"])

    def test_ilike_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="city", op=PredicateOperator.ILIKE, value="%york%"),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("places", intent)
        self.assertEqual(sql, 'SELECT * FROM "places" WHERE "city" ILIKE $1')
        self.assertEqual(params, ["%york%"])

    def test_in_predicate(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="status", op=PredicateOperator.IN, value=["A", "B", "C"]),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("orders", intent)
        self.assertEqual(sql, 'SELECT * FROM "orders" WHERE "status" IN ($1, $2, $3)')
        self.assertEqual(params, ["A", "B", "C"])

    def test_nested_or_group(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[
                    Predicate(field_id="active", op=PredicateOperator.EQ, value=True),
                    PredicateGroup(
                        op="OR",
                        predicates=[
                            Predicate(field_id="role", op=PredicateOperator.EQ, value="admin"),
                            Predicate(field_id="role", op=PredicateOperator.EQ, value="editor"),
                        ],
                    ),
                ],
            ),
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(
            sql,
            'SELECT * FROM "users" WHERE "active" = $1 AND ("role" = $2 OR "role" = $3)',
        )
        self.assertEqual(params, [True, "admin", "editor"])

    def test_with_projections(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="age", op=PredicateOperator.GT, value=0)],
            ),
            projections=["name", "email"],
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertTrue(sql.startswith('SELECT "name", "email" FROM'))

    def test_with_order_by(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="age", op=PredicateOperator.GT, value=0)],
            ),
            order_by=[
                SortOrder(field_id="name", direction="ASC"),
                SortOrder(field_id="age", direction="DESC"),
            ],
        )
        sql, _ = self.backend._build_query_sql("users", intent)
        self.assertIn('ORDER BY "name" ASC, "age" DESC', sql)

    def test_with_limit(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="age", op=PredicateOperator.GT, value=0)],
            ),
            limit=25,
        )
        sql, _ = self.backend._build_query_sql("users", intent)
        self.assertTrue(sql.endswith("LIMIT 25"))

    def test_combined_order_limit_projections(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="active", op=PredicateOperator.EQ, value=True)],
            ),
            projections=["id", "name"],
            order_by=[SortOrder(field_id="name", direction="ASC")],
            limit=10,
        )
        sql, params = self.backend._build_query_sql("users", intent)
        self.assertEqual(
            sql,
            'SELECT "id", "name" FROM "users" WHERE "active" = $1' ' ORDER BY "name" ASC LIMIT 10',
        )
        self.assertEqual(params, [True])


# =============================================================================
# Predicate Edge Case Tests
# =============================================================================


class TestPredicateEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _StubRDBMSBackend(definition=_make_definition())

    def test_in_with_empty_list_raises(self) -> None:
        pred = Predicate(field_id="x", op=PredicateOperator.IN, value=[])
        params: list[Any] = []
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            self.backend._build_predicate(pred, params)

    def test_in_with_non_list_value_raises(self) -> None:
        pred = Predicate(field_id="x", op=PredicateOperator.IN, value="scalar")
        params: list[Any] = []
        with self.assertRaisesRegex(ValueError, "list value"):
            self.backend._build_predicate(pred, params)


# =============================================================================
# Intent Dispatch Tests
# =============================================================================


class TestIntentToSQL(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _StubRDBMSBackend(definition=_make_definition())

    def test_dispatch_lookup(self) -> None:
        intent = LookupIntent(resource_id=_RID, key=IdentityPredicate(field_id="id", value=1))
        sql, params = self.backend._intent_to_sql("t", intent)
        self.assertIn("WHERE", sql)
        self.assertEqual(params, [1])

    def test_dispatch_query(self) -> None:
        intent = QueryIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="a", op=PredicateOperator.EQ, value=1)],
            ),
        )
        sql, params = self.backend._intent_to_sql("t", intent)
        self.assertIn("WHERE", sql)
        self.assertEqual(params, [1])

    def test_dispatch_ingest_raises(self) -> None:
        intent = IngestIntent(resource_id=_RID, payload=[{"k": "v"}])
        with self.assertRaises(NotImplementedError):
            self.backend._intent_to_sql("t", intent)

    def test_dispatch_revise_raises(self) -> None:
        intent = ReviseIntent(
            resource_id=_RID,
            predicates=PredicateGroup(
                op="AND",
                predicates=[Predicate(field_id="id", op=PredicateOperator.EQ, value=1)],
            ),
            payload={"k": "v"},
        )
        with self.assertRaises(NotImplementedError):
            self.backend._intent_to_sql("t", intent)


# =============================================================================
# Password Injection Tests
# =============================================================================


class TestInjectPassword(unittest.TestCase):
    def test_simple_dsn_without_password(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "secret")
        self.assertEqual(result, "postgresql://user:secret@localhost/db")

    def test_simple_dsn_with_existing_password(self) -> None:
        result = _inject_password("postgresql://user:old@localhost/db", "new")
        self.assertEqual(result, "postgresql://user:new@localhost/db")

    def test_password_with_special_characters(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "p@ss:w0rd/foo")
        self.assertIn("p%40ss%3Aw0rd%2Ffoo", result)
        self.assertTrue(result.startswith("postgresql://user:"))
        self.assertIn("@localhost/db", result)

    def test_dsn_with_port(self) -> None:
        result = _inject_password("postgresql://user@localhost:5432/db", "secret")
        self.assertEqual(result, "postgresql://user:secret@localhost:5432/db")

    def test_dsn_with_port_and_existing_password(self) -> None:
        result = _inject_password("postgresql://user:old@localhost:5432/db", "new")
        self.assertEqual(result, "postgresql://user:new@localhost:5432/db")

    def test_dsn_without_host_returns_unchanged(self) -> None:
        result = _inject_password("not-a-url", "secret")
        self.assertEqual(result, "not-a-url")

    def test_password_with_at_sign(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "p@ss")
        # '@' in password must be encoded so it does not break URL parsing
        self.assertIn("p%40ss", result)
        self.assertEqual(result.count("@"), 1)  # only the delimiter @
