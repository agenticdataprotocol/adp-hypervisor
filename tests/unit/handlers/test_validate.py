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
from adp_hypervisor.manifest.policy import MandatoryFilterRule, OperationalRule, ResourcePolicy
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.protocol.errors import ResourceNotFoundError
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
        sources=[SourceDefinition(source="test_table", fields=fields)],
    )


def _mock_manifest(
    resource: CuratedResource | None = None,
    policy: ResourcePolicy | None = None,
) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.get_resource.return_value = resource
    index.get_policy.return_value = policy
    return index


def _make_query_params(
    resource_id: str = "com.acme:test_resource",
    predicates: list[dict[str, Any]] | None = None,
    projections: list[str] | None = None,
    order_by: list[dict[str, str]] | None = None,
    limit: int | None = None,
    logic_op: str = "AND",
) -> dict[str, Any]:
    if predicates is None:
        predicates = [{"fieldId": "name", "op": "EQ", "value": "test"}]
    intent: dict[str, Any] = {
        "intentClass": "QUERY",
        "predicates": {"op": logic_op, "predicates": predicates},
    }
    if projections is not None:
        intent["projections"] = projections
    if order_by is not None:
        intent["orderBy"] = order_by
    if limit is not None:
        intent["limit"] = limit
    return {"resourceId": resource_id, "intent": intent}


def _make_lookup_params(
    resource_id: str = "com.acme:test_resource",
    key_field: str = "id",
    key_value: str | int | bool = "123",
    projections: list[str] | None = None,
) -> dict[str, Any]:
    intent: dict[str, Any] = {
        "intentClass": "LOOKUP",
        "key": {"fieldId": key_field, "op": "EQ", "value": key_value},
    }
    if projections is not None:
        intent["projections"] = projections
    return {"resourceId": resource_id, "intent": intent}


def _make_ingest_params(
    resource_id: str = "com.acme:test_resource",
    payload: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if payload is None:
        payload = [{"id": "1", "name": "test"}]
    return {
        "resourceId": resource_id,
        "intent": {"intentClass": "INGEST", "payload": payload},
    }


def _make_revise_params(
    resource_id: str = "com.acme:test_resource",
    predicates: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if predicates is None:
        predicates = [{"fieldId": "id", "op": "EQ", "value": "123"}]
    if payload is None:
        payload = {"name": "updated"}
    return {
        "resourceId": resource_id,
        "intent": {
            "intentClass": "REVISE",
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
        handler = ValidateHandler(manifest_index=_mock_manifest())
        self.assertEqual(handler.method, "adp.validate")


# =============================================================================
# Valid Intent Tests
# =============================================================================


class TestValidateValidIntents(unittest.IsolatedAsyncioTestCase):
    async def test_valid_query(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_lookup(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_lookup_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_ingest(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_ingest_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_revise(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_revise_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_projections(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_query_params(projections=["id", "name"]))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_order_by(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(order_by=[{"fieldId": "name", "direction": "ASC"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_valid_query_with_limit(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
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
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "nonexistent", "op": "EQ", "value": "x"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(len(data["issues"]), 1)
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")
        self.assertEqual(data["issues"][0]["field"], "nonexistent")
        self.assertEqual(data["issues"][0]["severity"], "BLOCKING")

    async def test_lookup_unknown_key_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_lookup_params(key_field="unknown"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")
        self.assertEqual(data["issues"][0]["field"], "unknown")

    async def test_ingest_unknown_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_ingest_params(payload=[{"id": "1", "unknown_field": "val"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        issue_fields = [i["field"] for i in data["issues"]]
        self.assertIn("unknown_field", issue_fields)

    async def test_revise_unknown_predicate_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_revise_params(
                predicates=[{"fieldId": "nonexistent", "op": "EQ", "value": "x"}],
                payload={"name": "updated"},
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "nonexistent" for i in data["issues"]))

    async def test_revise_unknown_payload_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_revise_params(payload={"unknown_col": "updated"}))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "unknown_col" for i in data["issues"]))

    async def test_ingest_deduplicates_across_records(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
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
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "active", "op": "LIKE", "value": "true"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "INVALID_OPERATOR")
        self.assertEqual(data["issues"][0]["field"], "active")

    async def test_similar_on_string_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {
                        "fieldId": "name",
                        "op": "SIMILAR",
                        "value": {"text": "search text"},
                    }
                ]
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "INVALID_OPERATOR")

    async def test_gt_on_boolean_field(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "active", "op": "GT", "value": True}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        op_issues = [i for i in data["issues"] if i["code"] == "INVALID_OPERATOR"]
        self.assertEqual(len(op_issues), 1)

    async def test_valid_operator_no_issue(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "amount", "op": "GT", "value": 100}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_revise_invalid_operator(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_revise_params(
                predicates=[{"fieldId": "active", "op": "LIKE", "value": "true"}],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "INVALID_OPERATOR")


# =============================================================================
# Projection Validation Tests
# =============================================================================


class TestValidateProjections(unittest.IsolatedAsyncioTestCase):
    async def test_query_unknown_projection(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(_make_query_params(projections=["id", "nonexistent"]))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "nonexistent" for i in data["issues"]))

    async def test_lookup_unknown_projection(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
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
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(order_by=[{"fieldId": "unknown_sort", "direction": "ASC"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["field"] == "unknown_sort" for i in data["issues"]))


# =============================================================================
# Mandatory Filter Policy Tests
# =============================================================================


class TestValidateMandatoryFilter(unittest.IsolatedAsyncioTestCase):
    def _policy_with_mandatory(
        self,
        field_id: str = "id",
        op: PredicateOperator = PredicateOperator.EQ,
        value: str | int = "required_val",
    ) -> ResourcePolicy:
        return ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id=field_id,
                    op=op,
                    value=value,
                ),
            ],
        )

    async def test_query_missing_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        missing = [i for i in data["issues"] if i["code"] == "MISSING_REQUIRED_PREDICATE"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["field"], "id")
        self.assertEqual(missing[0]["severity"], "BLOCKING")

    async def test_query_with_matching_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "id", "op": "EQ", "value": "required_val"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_query_wrong_value_fails(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "id", "op": "EQ", "value": "wrong_val"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["code"] == "MISSING_REQUIRED_PREDICATE" for i in data["issues"]))

    async def test_query_wrong_operator_fails(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(
            _make_query_params(predicates=[{"fieldId": "id", "op": "NEQ", "value": "required_val"}])
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["code"] == "MISSING_REQUIRED_PREDICATE" for i in data["issues"]))

    async def test_lookup_matching_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_lookup_params(key_field="id", key_value="required_val"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_lookup_wrong_key_value_fails(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_lookup_params(key_field="id", key_value="other_val"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])

    async def test_ingest_skips_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_ingest_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_revise_missing_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_revise_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertTrue(any(i["code"] == "MISSING_REQUIRED_PREDICATE" for i in data["issues"]))

    async def test_revise_with_matching_mandatory_filter(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(
            _make_revise_params(
                predicates=[{"fieldId": "id", "op": "EQ", "value": "required_val"}],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_mandatory_filter_in_nested_group(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_mandatory()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        params: dict[str, Any] = {
            "resourceId": "com.acme:test_resource",
            "intent": {
                "intentClass": "QUERY",
                "predicates": {
                    "op": "AND",
                    "predicates": [
                        {"fieldId": "name", "op": "EQ", "value": "test"},
                        {
                            "op": "OR",
                            "predicates": [
                                {
                                    "fieldId": "id",
                                    "op": "EQ",
                                    "value": "required_val",
                                },
                            ],
                        },
                    ],
                },
            },
        }
        result = await handler.handle(params)

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)


# =============================================================================
# Operational Rule Tests
# =============================================================================


class TestValidateOperationalRule(unittest.IsolatedAsyncioTestCase):
    def _policy_with_limit(self, limit: int = 100) -> ResourcePolicy:
        return ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[OperationalRule(type="OPERATIONAL", enforce_limit=limit)],
        )

    async def test_query_exceeds_limit(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params(limit=200))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])  # WARNING, not BLOCKING
        self.assertIn("issues", data)
        self.assertEqual(data["issues"][0]["code"], "CARDINALITY_EXCEEDED")
        self.assertEqual(data["issues"][0]["severity"], "WARNING")

    async def test_query_no_limit_warns(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertIn("issues", data)
        self.assertEqual(data["issues"][0]["code"], "CARDINALITY_EXCEEDED")

    async def test_query_within_limit_no_issue(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params(limit=50))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_query_at_exact_limit_no_issue(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params(limit=100))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_lookup_ignores_enforce_limit(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_lookup_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_ingest_ignores_enforce_limit(self) -> None:
        resource = _make_resource()
        policy = self._policy_with_limit(100)
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_ingest_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)


# =============================================================================
# Resource Not Found Tests
# =============================================================================


class TestValidateResourceNotFound(unittest.IsolatedAsyncioTestCase):
    async def test_raises_resource_not_found(self) -> None:
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=None))
        with self.assertRaisesRegex(ResourceNotFoundError, "Resource not found"):
            await handler.handle(_make_query_params(resource_id="nonexistent:resource"))


# =============================================================================
# Edge Cases
# =============================================================================


class TestValidateEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_no_policy_no_issues(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=None))
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_policy_with_no_rules(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=None,
        )
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertNotIn("issues", data)

    async def test_resource_with_no_sources_empty_fields(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:empty",
            intent_classes=[IntentClass.QUERY],
            version=1,
            backend_id="test",
            sources=[],
        )
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
        result = await handler.handle(
            _make_query_params(
                resource_id="com.acme:empty",
                predicates=[{"fieldId": "name", "op": "EQ", "value": "test"}],
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        self.assertEqual(data["issues"][0]["code"], "FIELD_NOT_FOUND")

    async def test_multiple_issues_collected(self) -> None:
        resource = _make_resource()
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource))
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

    async def test_warning_only_is_still_valid(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[OperationalRule(type="OPERATIONAL", enforce_limit=10)],
        )
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params(limit=20))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertTrue(data["valid"])
        self.assertIn("issues", data)
        for issue in data["issues"]:
            self.assertEqual(issue["severity"], "WARNING")

    async def test_blocking_and_warning_combined(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id="id",
                    op=PredicateOperator.EQ,
                    value="required",
                ),
                OperationalRule(type="OPERATIONAL", enforce_limit=10),
            ],
        )
        handler = ValidateHandler(manifest_index=_mock_manifest(resource=resource, policy=policy))
        result = await handler.handle(_make_query_params(limit=20))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertFalse(data["valid"])
        severities = {i["severity"] for i in data["issues"]}
        self.assertIn("BLOCKING", severities)
        self.assertIn("WARNING", severities)
