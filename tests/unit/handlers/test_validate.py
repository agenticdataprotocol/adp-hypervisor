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

"""Tests for ValidateHandler."""

import unittest
from typing import Any
from unittest.mock import MagicMock

from adp_hypervisor.handlers.validate import (
    ValidateHandler,
    _collect_predicates,
    _get_operators_for_field,
)
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import ResourceNotFoundError, UnauthorizedError
from adp_hypervisor.protocol.types import (
    Field,
    FieldType,
    IntentClass,
    LogicOperator,
    Predicate,
    PredicateGroup,
    PredicateOperator,
)

# =============================================================================
# Test helpers
# =============================================================================


def _make_fields() -> list[Field]:
    return [
        Field(field_id="id", type=FieldType.STRING, description="Unique identifier"),
        Field(field_id="name", type=FieldType.STRING, description="Name"),
        Field(field_id="amount", type=FieldType.INTEGER, description="Amount"),
        Field(field_id="active", type=FieldType.BOOLEAN, description="Active flag"),
    ]


def _make_resource(
    resource_id: str = "com.acme:test_resource",
    fields: list[Field] | None = None,
) -> CuratedResource:
    if fields is None:
        fields = _make_fields()
    return CuratedResource(
        resource_id=resource_id,
        intent_classes=[
            IntentClass.QUERY,
            IntentClass.LOOKUP,
            IntentClass.INGEST,
            IntentClass.REVISE,
        ],
        version=1,
        description="Test resource",
        backend_id="test_backend",
        source_definition=SourceDefinition(source="test_table", fields=fields),
    )


def _mock_manifest(
    resource: CuratedResource | None = None,
) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.get_resource.return_value = resource
    return index


def _mock_policy_enforcer() -> PolicyEnforcer:
    enforcer = MagicMock(spec=PolicyEnforcer)
    enforcer.resolve_role.return_value = "default"
    enforcer.check_access.return_value = None
    return enforcer


def _make_query_params(
    resource_id: str = "com.acme:test_resource",
    predicates: list[dict[str, Any]] | None = None,
    projections: list[str] | None = None,
    order_by: list[dict[str, str]] | None = None,
    limit: int | None = None,
    logic_op: str = "AND",
) -> dict[str, Any]:
    if predicates is None:
        predicates = [
            {"fieldId": "name", "op": "EQ", "value": "test"},
            {"fieldId": "amount", "op": "GT", "value": 0},
        ]
    intent: dict[str, Any] = {
        "intentClass": "QUERY",
        "resourceId": resource_id,
        "predicates": {"op": logic_op, "predicates": predicates},
    }
    if projections is not None:
        intent["projections"] = projections
    if order_by is not None:
        intent["orderBy"] = order_by
    if limit is not None:
        intent["limit"] = limit
    return {"intent": intent}


def _make_lookup_params(
    resource_id: str = "com.acme:test_resource",
    key_field: str = "id",
    key_value: str | int | bool = "123",
    projections: list[str] | None = None,
) -> dict[str, Any]:
    intent: dict[str, Any] = {
        "intentClass": "LOOKUP",
        "resourceId": resource_id,
        "key": {"fieldId": key_field, "op": "EQ", "value": key_value},
    }
    if projections is not None:
        intent["projections"] = projections
    return {"intent": intent}


def _make_ingest_params(
    resource_id: str = "com.acme:test_resource",
    payload: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if payload is None:
        payload = [{"id": "1", "name": "test"}]
    return {
        "intent": {"intentClass": "INGEST", "resourceId": resource_id, "payload": payload},
    }


def _make_revise_params(
    resource_id: str = "com.acme:test_resource",
    predicates: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if predicates is None:
        predicates = [
            {"fieldId": "id", "op": "EQ", "value": "123"},
            {"fieldId": "name", "op": "EQ", "value": "old"},
        ]
    if payload is None:
        payload = {"name": "updated"}
    return {
        "intent": {
            "intentClass": "REVISE",
            "resourceId": resource_id,
            "predicates": {"op": "AND", "predicates": predicates},
            "payload": payload,
        },
    }


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestCollectPredicates(unittest.TestCase):
    def test_flat_predicates(self) -> None:
        group = PredicateGroup(
            op=LogicOperator.AND,
            predicates=[
                Predicate(field_id="a", op=PredicateOperator.EQ, value="1"),
                Predicate(field_id="b", op=PredicateOperator.GT, value=2),
            ],
        )
        result = _collect_predicates(group)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].field_id, "a")
        self.assertEqual(result[1].field_id, "b")

    def test_nested_predicates(self) -> None:
        group = PredicateGroup(
            op=LogicOperator.AND,
            predicates=[
                Predicate(field_id="a", op=PredicateOperator.EQ, value="1"),
                PredicateGroup(
                    op=LogicOperator.OR,
                    predicates=[
                        Predicate(field_id="b", op=PredicateOperator.GT, value=2),
                        Predicate(field_id="c", op=PredicateOperator.LT, value=3),
                    ],
                ),
            ],
        )
        result = _collect_predicates(group)
        self.assertEqual(len(result), 3)
        field_ids = [p.field_id for p in result]
        self.assertEqual(field_ids, ["a", "b", "c"])

    def test_empty_group(self) -> None:
        group = PredicateGroup(op=LogicOperator.AND, predicates=[])
        result = _collect_predicates(group)
        self.assertEqual(result, [])


# =============================================================================
# Operator Mapping Tests
# =============================================================================


class TestGetOperatorsForField(unittest.TestCase):
    def test_string_type(self) -> None:
        ops = _get_operators_for_field(FieldType.STRING)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.LIKE, ops)
        self.assertNotIn(PredicateOperator.SIMILAR, ops)

    def test_integer_type(self) -> None:
        ops = _get_operators_for_field(FieldType.INTEGER)
        self.assertIn(PredicateOperator.GT, ops)
        self.assertNotIn(PredicateOperator.LIKE, ops)

    def test_boolean_type(self) -> None:
        ops = _get_operators_for_field(FieldType.BOOLEAN)
        self.assertEqual(ops, [PredicateOperator.EQ, PredicateOperator.NEQ])

    def test_vector_type(self) -> None:
        ops = _get_operators_for_field(FieldType.VECTOR)
        self.assertEqual(ops, [PredicateOperator.SIMILAR])


# =============================================================================
# Method Name Test
# =============================================================================


class TestValidateHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = ValidateHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        self.assertEqual(handler.method, "adp.validate")


# =============================================================================
# Valid Intent Tests
# =============================================================================


class TestValidateValidIntents(unittest.IsolatedAsyncioTestCase):
    async def test_valid_query(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_lookup(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_lookup_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_ingest(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_ingest_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_revise(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_revise_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_projections(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params(projections=["id", "name"]))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_order_by(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(order_by=[{"fieldId": "name", "direction": "ASC"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_limit(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params(limit=10))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)


# =============================================================================
# Field Not Found Tests
# =============================================================================


class TestValidateFieldNotFound(unittest.IsolatedAsyncioTestCase):
    async def test_query_predicate_unknown_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "nonexistent", "op": "EQ", "value": "x"},
                    {"fieldId": "name", "op": "EQ", "value": "ok"},
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        fnf_issues = [i for i in data["issues"] if i["code"] == "FIELD_NOT_FOUND"]
        self.assertEqual(len(fnf_issues), 1)
        self.assertEqual(fnf_issues[0]["field"], "nonexistent")
        self.assertEqual(fnf_issues[0]["severity"], "BLOCKING")

    async def test_lookup_unknown_key_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_lookup_params(key_field="unknown"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")
        self.assertEqual(data["issues"][0]["field"], "unknown")

    async def test_ingest_unknown_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_ingest_params(payload=[{"id": "1", "unknown_field": "val"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issue_fields = [i["field"] for i in data["issues"]]
        self.assertIn("unknown_field", issue_fields)

    async def test_revise_unknown_predicate_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_revise_params(
                predicates=[
                    {"fieldId": "nonexistent", "op": "EQ", "value": "x"},
                    {"fieldId": "id", "op": "EQ", "value": "1"},
                ],
                payload={"name": "updated"},
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "nonexistent" for i in data["issues"]))

    async def test_revise_unknown_payload_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_revise_params(payload={"unknown_col": "updated"}))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "unknown_col" for i in data["issues"]))

    async def test_ingest_deduplicates_across_records(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_ingest_params(payload=[{"bad_field": "v1"}, {"bad_field": "v2"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        bad_issues = [i for i in data["issues"] if i["field"] == "bad_field"]
        self.assertEqual(len(bad_issues), 1)


# =============================================================================
# Invalid Operator Tests
# =============================================================================


class TestValidateInvalidOperator(unittest.IsolatedAsyncioTestCase):
    async def test_like_on_boolean_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "active", "op": "LIKE", "value": "true"},
                    {"fieldId": "name", "op": "EQ", "value": "ok"},
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        op_issues = [i for i in data["issues"] if i["code"] == "INVALID_OPERATOR"]
        self.assertEqual(len(op_issues), 1)
        self.assertEqual(op_issues[0]["field"], "active")

    async def test_similar_on_string_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "name",
                        "op": "SIMILAR",
                        "value": {"vector": [0.1, 0.2, 0.3]},
                    },
                    {"fieldId": "amount", "op": "GT", "value": 0},
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        op_issues = [i for i in data["issues"] if i["code"] == "INVALID_OPERATOR"]
        self.assertEqual(len(op_issues), 1)

    async def test_gt_on_boolean_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "active", "op": "GT", "value": True},
                    {"fieldId": "name", "op": "EQ", "value": "ok"},
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        op_issues = [i for i in data["issues"] if i["code"] == "INVALID_OPERATOR"]
        self.assertEqual(len(op_issues), 1)

    async def test_valid_operator_no_issue(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "amount", "op": "GT", "value": 100},
                    {"fieldId": "name", "op": "EQ", "value": "ok"},
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_revise_invalid_operator(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_revise_params(
                predicates=[
                    {"fieldId": "active", "op": "LIKE", "value": "true"},
                    {"fieldId": "name", "op": "EQ", "value": "ok"},
                ],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        op_issues = [i for i in data["issues"] if i["code"] == "INVALID_OPERATOR"]
        self.assertEqual(len(op_issues), 1)


# =============================================================================
# Predicate Value Validation Tests
# =============================================================================


def _make_fields_with_vector() -> list[Field]:
    return _make_fields() + [
        Field(
            field_id="embedding",
            type=FieldType.VECTOR,
            description="Vector embedding",
        ),
    ]


class TestPredicateValueValidation(unittest.IsolatedAsyncioTestCase):
    async def test_similar_with_bare_list_reports_invalid_value(self) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "embedding",
                        "op": "SIMILAR",
                        "value": [0.1, 0.9, 0.3],
                    },
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issues = [i for i in data["issues"] if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "embedding")
        self.assertEqual(issues[0]["severity"], "BLOCKING")
        self.assertIn("correctionHint", issues[0])
        self.assertIn("message", issues[0])

    async def test_similar_with_empty_similar_value_reports_invalid_value(
        self,
    ) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "embedding",
                        "op": "SIMILAR",
                        "value": {},
                    },
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issues = [i for i in data["issues"] if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "embedding")
        self.assertEqual(issues[0]["severity"], "BLOCKING")
        self.assertIn("correctionHint", issues[0])
        self.assertIn("message", issues[0])

    async def test_similar_with_valid_vector_value(self) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "embedding",
                        "op": "SIMILAR",
                        "value": {"vector": [0.1, 0.9, 0.3]},
                    },
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        value_issues = [i for i in data.get("issues", []) if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(value_issues), 0)

    async def test_similar_with_valid_vector_and_top(self) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "embedding",
                        "op": "SIMILAR",
                        "value": {"vector": [0.1, 0.9, 0.3], "top": 5},
                    },
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        value_issues = [i for i in data.get("issues", []) if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(value_issues), 0)

    async def test_similar_with_scalar_value_reports_invalid_value(self) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "embedding",
                        "op": "SIMILAR",
                        "value": "test",
                    },
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issues = [i for i in data["issues"] if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "embedding")
        self.assertEqual(issues[0]["severity"], "BLOCKING")
        self.assertIn("correctionHint", issues[0])
        self.assertIn("message", issues[0])

    async def test_similar_value_check_with_bare_predicate(self) -> None:
        resource = _make_resource(fields=_make_fields_with_vector())
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params_bare_predicate(
                field_id="embedding",
                op="SIMILAR",
                value=[0.1, 0.9, 0.3],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issues = [i for i in data["issues"] if i["code"] == "INVALID_VALUE"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "embedding")
        self.assertEqual(issues[0]["severity"], "BLOCKING")
        self.assertIn("correctionHint", issues[0])
        self.assertIn("message", issues[0])


# =============================================================================
# Projection Validation Tests
# =============================================================================


class TestValidateProjections(unittest.IsolatedAsyncioTestCase):
    async def test_query_unknown_projection(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params(projections=["id", "nonexistent"]))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "nonexistent" for i in data["issues"]))

    async def test_lookup_unknown_projection(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_lookup_params(projections=["id", "ghost"]))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "ghost" for i in data["issues"]))


# =============================================================================
# Order By Validation Tests
# =============================================================================


class TestValidateOrderBy(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_order_by_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(order_by=[{"fieldId": "unknown_sort", "direction": "ASC"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "unknown_sort" for i in data["issues"]))


# =============================================================================
# Resource Not Found Tests
# =============================================================================


class TestValidateResourceNotFound(unittest.IsolatedAsyncioTestCase):
    async def test_raises_resource_not_found(self) -> None:
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=None), policy_enforcer=_mock_policy_enforcer()
        )
        with self.assertRaisesRegex(ResourceNotFoundError, "Resource not found"):
            await handler.handle(_make_query_params(resource_id="nonexistent:resource"))


# =============================================================================
# Edge Cases
# =============================================================================


class TestValidateEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_resource_with_no_fields(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:empty",
            intent_classes=[IntentClass.QUERY],
            version=1,
            backend_id="test",
            source_definition=SourceDefinition(source="empty_table"),
        )
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                resource_id="com.acme:empty",
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "test"},
                    {"fieldId": "id", "op": "EQ", "value": "1"},
                ],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        fnf_issues = [i for i in data["issues"] if i["code"] == "FIELD_NOT_FOUND"]
        self.assertGreaterEqual(len(fnf_issues), 1)

    async def test_multiple_issues_collected(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "nonexistent1", "op": "EQ", "value": "x"},
                    {"fieldId": "active", "op": "LIKE", "value": "y"},
                ],
                projections=["nonexistent2"],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertGreaterEqual(len(data["issues"]), 3)


# =============================================================================
# Logic Operator Arity Validation Tests
# =============================================================================


class TestValidateLogicOperatorArity(unittest.IsolatedAsyncioTestCase):
    """Validate that PredicateGroup logic operators have correct arity.

    AND/OR require >= 1 operand; NOT requires exactly 1.
    """

    async def test_and_with_two_predicates_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "a"},
                    {"fieldId": "amount", "op": "GT", "value": 1},
                ],
                logic_op="AND",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_and_with_single_predicate_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[{"fieldId": "name", "op": "EQ", "value": "a"}],
                logic_op="AND",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_or_with_two_predicates_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "a"},
                    {"fieldId": "name", "op": "EQ", "value": "b"},
                ],
                logic_op="OR",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])

    async def test_or_with_single_predicate_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[{"fieldId": "name", "op": "EQ", "value": "a"}],
                logic_op="OR",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_not_with_single_predicate_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[{"fieldId": "name", "op": "EQ", "value": "a"}],
                logic_op="NOT",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])

    async def test_not_with_two_predicates_invalid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "a"},
                    {"fieldId": "amount", "op": "GT", "value": 1},
                ],
                logic_op="NOT",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        fmt_issues = [i for i in data["issues"] if i["code"] == "INVALID_FORMAT"]
        self.assertEqual(len(fmt_issues), 1)
        self.assertIn("NOT", fmt_issues[0]["message"])

    async def test_not_wrapping_group_valid(self) -> None:
        """NOT (A AND B) is valid."""
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        params: dict[str, Any] = {
            "intent": {
                "intentClass": "QUERY",
                "resourceId": "com.acme:test_resource",
                "predicates": {
                    "op": "NOT",
                    "predicates": [
                        {
                            "op": "AND",
                            "predicates": [
                                {"fieldId": "name", "op": "EQ", "value": "a"},
                                {"fieldId": "amount", "op": "GT", "value": 1},
                            ],
                        }
                    ],
                },
            },
        }
        result = await handler.handle(params)

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])

    async def test_nested_invalid_group_detected(self) -> None:
        """AND with valid top level but nested NOT with 2 operands is invalid."""
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        params: dict[str, Any] = {
            "intent": {
                "intentClass": "QUERY",
                "resourceId": "com.acme:test_resource",
                "predicates": {
                    "op": "AND",
                    "predicates": [
                        {"fieldId": "name", "op": "EQ", "value": "a"},
                        {
                            "op": "NOT",
                            "predicates": [
                                {"fieldId": "amount", "op": "GT", "value": 1},
                                {"fieldId": "active", "op": "EQ", "value": True},
                            ],
                        },
                    ],
                },
            },
        }
        result = await handler.handle(params)

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        fmt_issues = [i for i in data["issues"] if i["code"] == "INVALID_FORMAT"]
        self.assertEqual(len(fmt_issues), 1)
        self.assertIn("NOT", fmt_issues[0]["message"])

    async def test_revise_logic_operator_validated(self) -> None:
        """REVISE intent also validates predicate group arity."""
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_revise_params(
                predicates=[{"fieldId": "id", "op": "EQ", "value": "123"}],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)


# =============================================================================
# Access Enforcement Tests
# =============================================================================


class TestValidateAccessEnforcement(unittest.IsolatedAsyncioTestCase):
    async def test_access_denied(self) -> None:
        """When check_access raises UnauthorizedError, handler propagates it."""
        resource = _make_resource()
        enforcer = _mock_policy_enforcer()
        enforcer.check_access.side_effect = UnauthorizedError("denied")
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource), policy_enforcer=enforcer
        )

        with self.assertRaises(UnauthorizedError) as ctx:
            await handler.handle(_make_query_params())
        self.assertEqual(ctx.exception.code, -32003)

    async def test_resolve_role_called(self) -> None:
        """Verify resolve_role is called with the params dict."""
        resource = _make_resource()
        enforcer = _mock_policy_enforcer()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource), policy_enforcer=enforcer
        )
        params = _make_query_params()

        await handler.handle(params)

        enforcer.resolve_role.assert_called_once_with(params)


# =============================================================================
# PredicateExpression Tests (bare Predicate as predicates)
# =============================================================================


def _make_query_params_bare_predicate(
    resource_id: str = "com.acme:test_resource",
    field_id: str = "name",
    op: str = "EQ",
    value: Any = "test",
    projections: list[str] | None = None,
) -> dict[str, Any]:
    """Build QUERY params using a bare Predicate (not a PredicateGroup)."""
    intent: dict[str, Any] = {
        "intentClass": "QUERY",
        "resourceId": resource_id,
        "predicates": {"fieldId": field_id, "op": op, "value": value},
    }
    if projections is not None:
        intent["projections"] = projections
    return {"intent": intent}


def _make_revise_params_bare_predicate(
    resource_id: str = "com.acme:test_resource",
    field_id: str = "id",
    op: str = "EQ",
    value: Any = "123",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build REVISE params using a bare Predicate (not a PredicateGroup)."""
    if payload is None:
        payload = {"name": "updated"}
    return {
        "intent": {
            "intentClass": "REVISE",
            "resourceId": resource_id,
            "predicates": {"fieldId": field_id, "op": op, "value": value},
            "payload": payload,
        },
    }


class TestPredicateExpression(unittest.IsolatedAsyncioTestCase):
    """Tests for bare Predicate (PredicateExpression) as intent predicates."""

    async def test_query_with_bare_predicate_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params_bare_predicate())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_query_with_bare_predicate_unknown_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_query_params_bare_predicate(field_id="nonexistent"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")

    async def test_revise_with_bare_predicate_valid(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_revise_params_bare_predicate())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_revise_with_bare_predicate_unknown_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_revise_params_bare_predicate(field_id="nonexistent"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")


class TestCollectPredicatesWithBarePredicate(unittest.TestCase):
    """Tests for _collect_predicates with bare Predicate input."""

    def test_bare_predicate(self) -> None:
        pred = Predicate(field_id="a", op=PredicateOperator.EQ, value="1")
        result = _collect_predicates(pred)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].field_id, "a")
