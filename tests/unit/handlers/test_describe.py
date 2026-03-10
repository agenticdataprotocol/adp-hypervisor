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

"""Tests for DescribeHandler."""

import unittest
from typing import Any
from unittest.mock import MagicMock

from adp_hypervisor.handlers.describe import (
    DescribeHandler,
    _build_read_capabilities,
    _build_write_capabilities,
    _get_operators_for_field,
)
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.policy import MandatoryFilterPolicy
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import (
    InvalidParamsError,
    ResourceNotFoundError,
    UnauthorizedError,
)
from adp_hypervisor.protocol.types import (
    Field,
    FieldType,
    PredicateOperator,
    PredicateUsage,
)


def _make_fields() -> list[Field]:
    return [
        Field(field_id="id", type=FieldType.STRING, description="Unique identifier"),
        Field(field_id="name", type=FieldType.STRING, description="Name"),
        Field(field_id="amount", type=FieldType.INTEGER, description="Amount"),
        Field(field_id="active", type=FieldType.BOOLEAN, description="Active flag"),
    ]


def _make_resource(
    resource_id: str = "com.acme:test_resource",
    intent_classes: list[str] = ["QUERY", "LOOKUP"],  # noqa: B006  # required per spec
    version: int = 1,
    fields: list[Field] | None = None,
) -> CuratedResource:
    if fields is None:
        fields = _make_fields()
    return CuratedResource(
        resource_id=resource_id,
        intent_classes=intent_classes,
        version=version,
        description="Test resource",
        backend_id="test_backend",
        source_definition=SourceDefinition(source="test_table", fields=fields),
    )


def _mock_manifest(
    resource: CuratedResource | None = None,
    mandatory_filters: list[MandatoryFilterPolicy] | None = None,
) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.get_resource.return_value = resource
    index.get_mandatory_filter_policies.return_value = mandatory_filters or []
    return index


def _mock_policy_enforcer() -> PolicyEnforcer:
    enforcer = MagicMock(spec=PolicyEnforcer)
    enforcer.resolve_role.return_value = "default"
    enforcer.check_access.return_value = None
    return enforcer


def _make_params(
    resource_id: str = "com.acme:test_resource",
    intent_class: str = "QUERY",
    version: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "resourceId": resource_id,
        "intentClass": intent_class,
    }
    if version is not None:
        params["version"] = version
    return params


# =============================================================================
# Operator Mapping Tests
# =============================================================================


class TestOperatorMapping(unittest.TestCase):
    def test_string_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.STRING)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.LIKE, ops)
        self.assertIn(PredicateOperator.ILIKE, ops)
        self.assertIn(PredicateOperator.IN, ops)
        self.assertIn(PredicateOperator.CONTAINS, ops)
        self.assertNotIn(PredicateOperator.SIMILAR, ops)

    def test_integer_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.INTEGER)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.GT, ops)
        self.assertIn(PredicateOperator.IN, ops)
        self.assertNotIn(PredicateOperator.LIKE, ops)
        self.assertNotIn(PredicateOperator.SIMILAR, ops)

    def test_float_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.FLOAT)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.LTE, ops)
        self.assertIn(PredicateOperator.IN, ops)
        self.assertNotIn(PredicateOperator.LIKE, ops)

    def test_boolean_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.BOOLEAN)
        self.assertEqual(ops, [PredicateOperator.EQ, PredicateOperator.NEQ])

    def test_vector_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.VECTOR)
        self.assertEqual(ops, [PredicateOperator.SIMILAR])

    def test_date_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.DATE)
        self.assertIn(PredicateOperator.GT, ops)
        self.assertIn(PredicateOperator.LTE, ops)
        self.assertIn(PredicateOperator.LIKE, ops)

    def test_timestamp_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.TIMESTAMP)
        self.assertIn(PredicateOperator.GT, ops)
        self.assertIn(PredicateOperator.ILIKE, ops)

    def test_blob_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.BLOB)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.CONTAINS, ops)
        self.assertNotIn(PredicateOperator.LIKE, ops)

    def test_json_operators(self) -> None:
        ops = _get_operators_for_field(FieldType.JSON)
        self.assertIn(PredicateOperator.EQ, ops)
        self.assertIn(PredicateOperator.CONTAINS, ops)
        self.assertNotIn(PredicateOperator.LIKE, ops)


# =============================================================================
# Capability Builder Tests
# =============================================================================


# =============================================================================
# Build Read Capabilities Tests
# =============================================================================


class TestBuildReadCapabilities(unittest.TestCase):
    def test_generates_predicates_for_all_fields(self) -> None:
        fields = _make_fields()
        caps = _build_read_capabilities(fields, set())
        self.assertIsNotNone(caps.predicates)
        assert caps.predicates is not None
        self.assertEqual(len(caps.predicates), len(fields))

    def test_all_predicates_optional_by_default(self) -> None:
        fields = _make_fields()
        caps = _build_read_capabilities(fields, set())
        self.assertIsNotNone(caps.predicates)
        assert caps.predicates is not None
        for pred in caps.predicates:
            self.assertEqual(pred.usage, PredicateUsage.OPTIONAL)

    def test_mandatory_field_becomes_required(self) -> None:
        fields = _make_fields()
        caps = _build_read_capabilities(fields, {"id"})
        self.assertIsNotNone(caps.predicates)
        assert caps.predicates is not None
        id_pred = next(p for p in caps.predicates if p.field_id == "id")
        self.assertEqual(id_pred.usage, PredicateUsage.REQUIRED)
        name_pred = next(p for p in caps.predicates if p.field_id == "name")
        self.assertEqual(name_pred.usage, PredicateUsage.OPTIONAL)

    def test_generates_projections_for_all_fields(self) -> None:
        fields = _make_fields()
        caps = _build_read_capabilities(fields, set())
        self.assertIsNotNone(caps.projections)
        assert caps.projections is not None
        self.assertEqual(len(caps.projections), len(fields))
        field_ids = {p.field_id for p in caps.projections}
        self.assertEqual(field_ids, {"id", "name", "amount", "active"})

    def test_mutables_not_set(self) -> None:
        caps = _build_read_capabilities(_make_fields(), set())
        self.assertIsNone(caps.mutables)

    def test_operators_match_field_type(self) -> None:
        fields = _make_fields()
        caps = _build_read_capabilities(fields, set())
        self.assertIsNotNone(caps.predicates)
        assert caps.predicates is not None
        bool_pred = next(p for p in caps.predicates if p.field_id == "active")
        self.assertEqual(bool_pred.operators, [PredicateOperator.EQ, PredicateOperator.NEQ])


# =============================================================================
# Build Write Capabilities Tests
# =============================================================================


class TestBuildWriteCapabilities(unittest.TestCase):
    def test_generates_mutables_for_all_fields(self) -> None:
        fields = _make_fields()
        caps = _build_write_capabilities(fields)
        self.assertIsNotNone(caps.mutables)
        assert caps.mutables is not None
        self.assertEqual(len(caps.mutables), len(fields))
        field_ids = {m.field_id for m in caps.mutables}
        self.assertEqual(field_ids, {"id", "name", "amount", "active"})

    def test_predicates_not_set(self) -> None:
        caps = _build_write_capabilities(_make_fields())
        self.assertIsNone(caps.predicates)

    def test_projections_not_set(self) -> None:
        caps = _build_write_capabilities(_make_fields())
        self.assertIsNone(caps.projections)


# =============================================================================
# Method Name Test
# =============================================================================


class TestDescribeHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = DescribeHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        self.assertEqual(handler.method, "adp.describe")


# =============================================================================
# Basic Describe Tests
# =============================================================================


class TestDescribeHandlerBasic(unittest.IsolatedAsyncioTestCase):
    async def test_returns_describe_result(self) -> None:
        resource = _make_resource()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resourceId"], "com.acme:test_resource")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["intentClass"], "QUERY")
        self.assertIn("usageContract", data)
        self.assertIn("fields", data["usageContract"])
        self.assertIn("capabilities", data["usageContract"])

    async def test_returns_fields_from_source(self) -> None:
        resource = _make_resource()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        field_ids = [f["fieldId"] for f in data["usageContract"]["fields"]]
        self.assertEqual(field_ids, ["id", "name", "amount", "active"])

    async def test_read_intent_generates_predicates_and_projections(self) -> None:
        resource = _make_resource()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        caps = data["usageContract"]["capabilities"]
        self.assertIn("predicates", caps)
        self.assertIn("projections", caps)
        self.assertNotIn("mutables", caps)

    async def test_write_intent_generates_mutables(self) -> None:
        resource = _make_resource(intent_classes=["INGEST"])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="INGEST"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        caps = data["usageContract"]["capabilities"]
        self.assertIn("mutables", caps)
        self.assertNotIn("predicates", caps)
        self.assertNotIn("projections", caps)

    async def test_revise_generates_mutables(self) -> None:
        resource = _make_resource(intent_classes=["REVISE"])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="REVISE"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        caps = data["usageContract"]["capabilities"]
        self.assertIn("mutables", caps)

    async def test_lookup_generates_predicates_and_projections(self) -> None:
        resource = _make_resource(intent_classes=["LOOKUP"])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="LOOKUP"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        caps = data["usageContract"]["capabilities"]
        self.assertIn("predicates", caps)
        self.assertIn("projections", caps)


# =============================================================================
# Version Query Tests
# =============================================================================


class TestDescribeHandlerVersionQuery(unittest.IsolatedAsyncioTestCase):
    async def test_version_passed_to_manifest(self) -> None:
        resource = _make_resource(version=2)
        manifest = _mock_manifest(resource=resource)
        handler = DescribeHandler(manifest_index=manifest, policy_enforcer=_mock_policy_enforcer())
        await handler.handle(_make_params(version=2))

        manifest.get_resource.assert_called_once_with("com.acme:test_resource", version=2)

    async def test_no_version_returns_latest(self) -> None:
        resource = _make_resource(version=3)
        manifest = _mock_manifest(resource=resource)
        handler = DescribeHandler(manifest_index=manifest, policy_enforcer=_mock_policy_enforcer())
        result = await handler.handle(_make_params())

        manifest.get_resource.assert_called_once_with("com.acme:test_resource", version=None)
        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["version"], 3)


# =============================================================================
# Resource Not Found Tests
# =============================================================================


class TestDescribeHandlerResourceNotFound(unittest.IsolatedAsyncioTestCase):
    async def test_resource_not_found_raises(self) -> None:
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=None), policy_enforcer=_mock_policy_enforcer()
        )
        with self.assertRaisesRegex(ResourceNotFoundError, "Resource not found"):
            await handler.handle(_make_params(resource_id="nonexistent:resource"))

    async def test_version_not_found_raises(self) -> None:
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=None), policy_enforcer=_mock_policy_enforcer()
        )
        with self.assertRaisesRegex(ResourceNotFoundError, "version=99"):
            await handler.handle(_make_params(version=99))


# =============================================================================
# Intent Class Validation Tests
# =============================================================================


class TestDescribeHandlerIntentClassValidation(unittest.IsolatedAsyncioTestCase):
    async def test_wildcard_intent_class_rejected(self) -> None:
        resource = _make_resource()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        with self.assertRaisesRegex(InvalidParamsError, r"WILDCARD.*not allowed"):
            await handler.handle(_make_params(intent_class="*"))

    async def test_unsupported_intent_class_rejected(self) -> None:
        resource = _make_resource(intent_classes=["QUERY"])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        with self.assertRaisesRegex(InvalidParamsError, "does not support intent class"):
            await handler.handle(_make_params(intent_class="INGEST"))

    async def test_wildcard_resource_accepts_any_intent(self) -> None:
        resource = _make_resource(intent_classes=["*"])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["intentClass"], "QUERY")

    async def test_resource_with_empty_intent_classes_rejected(self) -> None:
        resource = _make_resource(intent_classes=[])
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        with self.assertRaisesRegex(InvalidParamsError, "does not declare"):
            await handler.handle(_make_params(intent_class="QUERY"))


# =============================================================================
# Policy Integration Tests
# =============================================================================


class TestDescribeHandlerPolicyIntegration(unittest.IsolatedAsyncioTestCase):
    # NOTE: Policy enforcement is disabled until the policy spec is finalized.
    # All predicates are OPTIONAL regardless of policy rules.

    async def test_operational_policy_does_not_affect_predicates(self) -> None:
        """OPERATIONAL policy has no effect on predicate usage (all remain OPTIONAL)."""
        resource = _make_resource()
        # No mandatory filters — only operational policy in this test
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        predicates = data["usageContract"]["capabilities"]["predicates"]
        for pred in predicates:
            self.assertEqual(pred["usage"], "OPTIONAL")

    async def test_no_policy_all_predicates_optional(self) -> None:
        resource = _make_resource()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        predicates = data["usageContract"]["capabilities"]["predicates"]
        for pred in predicates:
            self.assertEqual(pred["usage"], "OPTIONAL")

    async def test_write_intent_ignores_mandatory_filter(self) -> None:
        """MANDATORY_FILTER policy has no effect on write (INGEST) capability output."""
        resource = _make_resource(intent_classes=["INGEST"])
        mf_policy = MandatoryFilterPolicy(
            type="MANDATORY_FILTER",
            resource_id="com.acme:test_resource",
            field_id="id",
            op="EQ",
            value="v",
        )
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource, mandatory_filters=[mf_policy]),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="INGEST"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        caps = data["usageContract"]["capabilities"]
        self.assertIn("mutables", caps)
        self.assertNotIn("predicates", caps)


# =============================================================================
# Edge Cases
# =============================================================================


class TestDescribeHandlerEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_resource_with_empty_fields_returns_empty_fields(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:empty",
            intent_classes=["QUERY"],
            version=1,
            backend_id="test",
            source_definition=SourceDefinition(source="empty", fields=[]),
        )
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_params(resource_id="com.acme:empty", intent_class="QUERY")
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["usageContract"]["fields"], [])

    async def test_resource_with_source_but_no_fields(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:no_fields",
            intent_classes=["QUERY"],
            version=1,
            backend_id="test",
            source_definition=SourceDefinition(source="empty_table", fields=None),
        )
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(
            _make_params(resource_id="com.acme:no_fields", intent_class="QUERY")
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["usageContract"]["fields"], [])

    async def test_vector_field_gets_similar_operator(self) -> None:
        fields = [Field(field_id="embedding", type=FieldType.VECTOR)]
        resource = _make_resource(fields=fields)
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        predicates = data["usageContract"]["capabilities"]["predicates"]
        self.assertEqual(predicates[0]["operators"], ["SIMILAR"])

    async def test_resource_version_defaults_to_one(self) -> None:
        resource = _make_resource()
        resource.version = None
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["version"], 1)


# =============================================================================
# Access Enforcement Tests
# =============================================================================


class TestDescribeAccessEnforcement(unittest.IsolatedAsyncioTestCase):
    async def test_access_denied(self) -> None:
        """When check_access raises UnauthorizedError, handler propagates it."""
        resource = _make_resource()
        enforcer = _mock_policy_enforcer()
        enforcer.check_access.side_effect = UnauthorizedError("denied")
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource), policy_enforcer=enforcer
        )

        with self.assertRaises(UnauthorizedError) as ctx:
            await handler.handle(_make_params())
        self.assertEqual(ctx.exception.code, -32003)

    async def test_resolve_role_called(self) -> None:
        """Verify resolve_role is called with the params dict."""
        resource = _make_resource()
        enforcer = _mock_policy_enforcer()
        handler = DescribeHandler(
            manifest_index=_mock_manifest(resource=resource), policy_enforcer=enforcer
        )
        params = _make_params()

        await handler.handle(params)

        enforcer.resolve_role.assert_called_once_with(params)
