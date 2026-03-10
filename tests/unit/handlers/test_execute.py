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

"""Tests for ExecuteHandler."""

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from adp_hypervisor.handlers.execute import ExecuteHandler
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import (
    ExecutionFailedError,
    ResourceNotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from adp_hypervisor.protocol.types import (
    Field,
    FieldType,
    IntentClass,
)
from backends.base import Backend, BackendResult
from backends.registry import BackendRegistry

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
    backend_id: str = "test_backend",
    source: str = "test_table",
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
        backend_id=backend_id,
        source_definition=SourceDefinition(source=source, fields=fields),
    )


def _mock_manifest(
    resource: CuratedResource | None = None,
) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.get_resource.return_value = resource
    return index


def _mock_backend(
    backend_id: str = "test_backend",
    rows: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Backend:
    backend = AsyncMock(spec=Backend)
    backend.backend_id = backend_id
    result = BackendResult(rows=rows or [], metadata=metadata or {})
    backend.execute.return_value = result
    return backend


def _mock_registry(backend: Backend | None = None) -> BackendRegistry:
    registry = MagicMock(spec=BackendRegistry)
    registry.get.return_value = backend
    return registry


def _mock_policy_enforcer() -> PolicyEnforcer:
    enforcer = MagicMock(spec=PolicyEnforcer)
    enforcer.resolve_role.return_value = "default"
    enforcer.check_access.return_value = None
    return enforcer


def _make_handler(
    resource: CuratedResource | None = None,
    backend: Backend | None = None,
) -> ExecuteHandler:
    """Create an ExecuteHandler with mocked dependencies."""
    if resource is None:
        resource = _make_resource()
    manifest = _mock_manifest(resource=resource)
    if backend is None:
        backend = _mock_backend()
    registry = _mock_registry(backend)
    return ExecuteHandler(
        manifest_index=manifest, backend_registry=registry, policy_enforcer=_mock_policy_enforcer()
    )


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
    if len(predicates) == 1:
        predicates = [*predicates, {"fieldId": "id", "op": "EQ", "value": "1"}]
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
        predicates = [{"fieldId": "id", "op": "EQ", "value": "123"}]
    if len(predicates) == 1:
        predicates = [*predicates, {"fieldId": "active", "op": "EQ", "value": True}]
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
# Method Name Test
# =============================================================================


class TestExecuteHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = _make_handler()
        self.assertEqual(handler.method, "adp.execute")


# =============================================================================
# Successful Execution Tests
# =============================================================================


class TestExecuteSuccess(unittest.IsolatedAsyncioTestCase):
    async def test_query_returns_results(self) -> None:
        rows = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)
        self.assertIn("executionMetadata", data)
        self.assertIn("durationMs", data["executionMetadata"])
        self.assertEqual(data["executionMetadata"]["sourceSystem"], "test_backend")

    async def test_lookup_returns_single_result(self) -> None:
        rows = [{"id": "123", "name": "Alice"}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_lookup_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)

    async def test_ingest_returns_empty_results(self) -> None:
        backend = _mock_backend(rows=[])
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_ingest_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], [])

    async def test_revise_returns_results(self) -> None:
        rows = [{"id": "123", "name": "updated"}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_revise_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)

    async def test_execution_metadata_includes_duration(self) -> None:
        backend = _mock_backend(rows=[])
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertIsInstance(data["executionMetadata"]["durationMs"], int)
        self.assertGreaterEqual(data["executionMetadata"]["durationMs"], 0)

    async def test_next_cursor_is_none(self) -> None:
        """Pagination is not yet implemented; next_cursor should always be None."""
        backend = _mock_backend(rows=[{"id": "1"}])
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertNotIn("nextCursor", data)

    async def test_backend_called_with_correct_source(self) -> None:
        backend = _mock_backend()
        handler = _make_handler(backend=backend)

        await handler.handle(_make_query_params())

        backend.execute.assert_called_once()
        call_args = backend.execute.call_args
        # Backend should receive the Intent; resource → source mapping is handled
        # via the manifest index at backend level.
        intent_arg = call_args[0][0]
        self.assertEqual(intent_arg.resource_id, "com.acme:test_resource")

    async def test_query_with_projections(self) -> None:
        rows = [{"id": "1", "name": "Alice"}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params(projections=["id", "name"]))
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)


# =============================================================================
# Resource Not Found Tests
# =============================================================================


class TestExecuteResourceNotFound(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_resource_raises_error(self) -> None:
        manifest = _mock_manifest(resource=None)
        registry = _mock_registry()
        handler = ExecuteHandler(
            manifest_index=manifest,
            backend_registry=registry,
            policy_enforcer=_mock_policy_enforcer(),
        )

        with self.assertRaises(ResourceNotFoundError):
            await handler.handle(_make_query_params(resource_id="unknown:resource"))


# =============================================================================
# Validation Failure Tests
# =============================================================================


class TestExecuteValidationFailure(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_predicate_field_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError) as ctx:
            await handler.handle(
                _make_query_params(
                    predicates=[{"fieldId": "nonexistent", "op": "EQ", "value": "x"}]
                )
            )
        self.assertIn("issues", ctx.exception.data)

    async def test_invalid_operator_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError) as ctx:
            await handler.handle(
                _make_query_params(
                    predicates=[{"fieldId": "active", "op": "LIKE", "value": "test"}]
                )
            )
        issues = ctx.exception.data["issues"]
        self.assertTrue(any(i["code"] == "INVALID_OPERATOR" for i in issues))

    async def test_unknown_projection_field_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(_make_query_params(projections=["nonexistent_field"]))

    async def test_lookup_unknown_key_field_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(_make_lookup_params(key_field="unknown"))

    async def test_ingest_unknown_field_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(_make_ingest_params(payload=[{"unknown_field": "val"}]))

    async def test_revise_unknown_payload_field_raises_validation_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(_make_revise_params(payload={"nonexistent": "value"}))

    async def test_validation_failure_does_not_call_backend(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(
                _make_query_params(
                    predicates=[{"fieldId": "nonexistent", "op": "EQ", "value": "x"}]
                )
            )
        backend.execute.assert_not_called()


# =============================================================================
# Backend Error Tests
# =============================================================================


class TestExecuteBackendErrors(unittest.IsolatedAsyncioTestCase):
    async def test_backend_not_found_raises_execution_error(self) -> None:
        resource = _make_resource()
        manifest = _mock_manifest(resource=resource)
        registry = _mock_registry(backend=None)
        handler = ExecuteHandler(
            manifest_index=manifest,
            backend_registry=registry,
            policy_enforcer=_mock_policy_enforcer(),
        )

        with self.assertRaises(ExecutionFailedError) as ctx:
            await handler.handle(_make_query_params())
        self.assertIn("Backend not found", ctx.exception.message)

    async def test_backend_execute_exception_raises_execution_error(self) -> None:
        resource = _make_resource()
        backend = _mock_backend()
        backend.execute.side_effect = RuntimeError("connection lost")
        handler = _make_handler(resource=resource, backend=backend)

        with self.assertRaises(ExecutionFailedError) as ctx:
            await handler.handle(_make_query_params())
        self.assertIn("Execution failed", ctx.exception.message)

    async def test_resource_without_sources_raises_execution_error(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:no_sources",
            intent_classes=[IntentClass.QUERY],
            version=1,
            description="No sources",
            backend_id="test_backend",
            source_definition=SourceDefinition(source="", fields=[]),
        )
        backend = _mock_backend()
        # Build handler with direct mock to bypass validation (no fields → validation
        # would fail before reaching the source check). We test the source resolution
        # path in isolation by patching _validate_intent to be a no-op.
        handler = _make_handler(resource=resource, backend=backend)
        handler._validate_intent = AsyncMock()  # type: ignore[method-assign]

        with self.assertRaises(ExecutionFailedError) as ctx:
            await handler.handle(_make_query_params(resource_id="com.acme:no_sources"))
        # Error message should clearly indicate missing source definition.
        self.assertIn("missing source_definition.source", ctx.exception.message)


# =============================================================================
# Result Serialization Tests
# =============================================================================


class TestExecuteResultSerialization(unittest.IsolatedAsyncioTestCase):
    async def test_result_uses_camel_case_aliases(self) -> None:
        rows = [{"id": "1", "name": "Alice"}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertIn("results", data)
        self.assertIn("executionMetadata", data)
        self.assertIn("durationMs", data["executionMetadata"])
        self.assertIn("sourceSystem", data["executionMetadata"])
        self.assertNotIn("execution_metadata", data)
        self.assertNotIn("next_cursor", data)

    async def test_empty_results_serialization(self) -> None:
        backend = _mock_backend(rows=[])
        handler = _make_handler(backend=backend)

        result = await handler.handle(_make_query_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], [])
        self.assertIn("executionMetadata", data)


# =============================================================================
# Access Enforcement Tests
# =============================================================================


class TestExecuteAccessEnforcement(unittest.IsolatedAsyncioTestCase):
    async def test_access_denied_via_validation(self) -> None:
        """PolicyEnforcer UnauthorizedError during validation propagates."""
        resource = _make_resource()
        manifest = _mock_manifest(resource=resource)
        backend = _mock_backend()
        registry = _mock_registry(backend)
        enforcer = _mock_policy_enforcer()
        enforcer.check_access.side_effect = UnauthorizedError("denied")
        handler = ExecuteHandler(
            manifest_index=manifest, backend_registry=registry, policy_enforcer=enforcer
        )

        with self.assertRaises(UnauthorizedError) as ctx:
            await handler.handle(_make_query_params())
        self.assertEqual(ctx.exception.code, -32003)
        backend.execute.assert_not_called()
