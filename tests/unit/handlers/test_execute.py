"""Tests for ExecuteHandler."""

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from adp_hypervisor.handlers.execute import ExecuteHandler
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.policy import MandatoryFilterRule, OperationalRule, ResourcePolicy
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.protocol.errors import (
    ExecutionFailedError,
    ResourceNotFoundError,
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
        sources=[SourceDefinition(source=source, fields=fields)],
    )


def _mock_manifest(
    resource: CuratedResource | None = None,
    policy: ResourcePolicy | None = None,
) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.get_resource.return_value = resource
    index.get_policy.return_value = policy
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


def _make_handler(
    resource: CuratedResource | None = None,
    policy: ResourcePolicy | None = None,
    backend: Backend | None = None,
) -> ExecuteHandler:
    """Create an ExecuteHandler with mocked dependencies."""
    if resource is None:
        resource = _make_resource()
    manifest = _mock_manifest(resource=resource, policy=policy)
    if backend is None:
        backend = _mock_backend()
    registry = _mock_registry(backend)
    return ExecuteHandler(manifest_index=manifest, backend_registry=registry)


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
        self.assertEqual(call_args[0][0], "test_table")

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
        handler = ExecuteHandler(manifest_index=manifest, backend_registry=registry)

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
# Policy Enforcement Tests — Mandatory Filter
# =============================================================================


class TestExecuteMandatoryFilter(unittest.IsolatedAsyncioTestCase):
    async def test_missing_mandatory_filter_raises_validation_error(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id="active",
                    op="EQ",
                    value=True,
                ),
            ],
        )
        backend = _mock_backend()
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        with self.assertRaises(ValidationFailedError) as ctx:
            await handler.handle(_make_query_params())

        issues = ctx.exception.data["issues"]
        self.assertTrue(any(i["code"] == "MISSING_REQUIRED_PREDICATE" for i in issues))
        backend.execute.assert_not_called()

    async def test_matching_mandatory_filter_allows_execution(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id="active",
                    op="EQ",
                    value=True,
                ),
            ],
        )
        rows = [{"id": "1", "name": "Alice", "active": True}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "test"},
                    {"fieldId": "active", "op": "EQ", "value": True},
                ]
            )
        )
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)
        backend.execute.assert_called_once()


# =============================================================================
# Policy Enforcement Tests — Operational Rules (enforce_limit)
# =============================================================================


class TestExecuteOperationalRules(unittest.IsolatedAsyncioTestCase):
    async def test_limit_capped_to_enforce_limit(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                OperationalRule(type="OPERATIONAL", enforce_limit=50),
            ],
        )
        backend = _mock_backend(rows=[])
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        await handler.handle(_make_query_params(limit=100))

        call_args = backend.execute.call_args
        intent = call_args[0][1]
        self.assertEqual(intent.limit, 50)

    async def test_none_limit_capped_to_enforce_limit(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                OperationalRule(type="OPERATIONAL", enforce_limit=50),
            ],
        )
        backend = _mock_backend(rows=[])
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        await handler.handle(_make_query_params(limit=None))

        call_args = backend.execute.call_args
        intent = call_args[0][1]
        self.assertEqual(intent.limit, 50)

    async def test_limit_within_enforce_limit_unchanged(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                OperationalRule(type="OPERATIONAL", enforce_limit=100),
            ],
        )
        backend = _mock_backend(rows=[])
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        await handler.handle(_make_query_params(limit=50))

        call_args = backend.execute.call_args
        intent = call_args[0][1]
        self.assertEqual(intent.limit, 50)

    async def test_enforce_limit_only_applies_to_query(self) -> None:
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                OperationalRule(type="OPERATIONAL", enforce_limit=10),
            ],
        )
        backend = _mock_backend(rows=[{"id": "123", "name": "Alice"}])
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        result = await handler.handle(_make_lookup_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(len(data["results"]), 1)
        backend.execute.assert_called_once()

    async def test_no_policy_does_not_cap_limit(self) -> None:
        resource = _make_resource()
        backend = _mock_backend(rows=[])
        handler = _make_handler(resource=resource, policy=None, backend=backend)

        await handler.handle(_make_query_params(limit=1000))

        call_args = backend.execute.call_args
        intent = call_args[0][1]
        self.assertEqual(intent.limit, 1000)


# =============================================================================
# Backend Error Tests
# =============================================================================


class TestExecuteBackendErrors(unittest.IsolatedAsyncioTestCase):
    async def test_backend_not_found_raises_execution_error(self) -> None:
        resource = _make_resource()
        manifest = _mock_manifest(resource=resource)
        registry = _mock_registry(backend=None)
        handler = ExecuteHandler(manifest_index=manifest, backend_registry=registry)

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
        self.assertIn("connection lost", ctx.exception.message)

    async def test_resource_without_sources_raises_execution_error(self) -> None:
        resource = CuratedResource(
            resource_id="com.acme:no_sources",
            intent_classes=[IntentClass.QUERY],
            version=1,
            description="No sources",
            backend_id="test_backend",
            sources=[],
        )
        backend = _mock_backend()
        # Build handler with direct mock to bypass validation (no fields → validation
        # would fail before reaching the source check). We test the source resolution
        # path in isolation by patching _validate_intent to be a no-op.
        handler = _make_handler(resource=resource, backend=backend)
        handler._validate_intent = AsyncMock()  # type: ignore[method-assign]

        with self.assertRaises(ExecutionFailedError) as ctx:
            await handler.handle(_make_query_params(resource_id="com.acme:no_sources"))
        self.assertIn("no source definitions", ctx.exception.message)


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
# Combined Policy Rules Tests
# =============================================================================


class TestExecuteCombinedPolicyRules(unittest.IsolatedAsyncioTestCase):
    async def test_mandatory_filter_and_enforce_limit(self) -> None:
        """Both mandatory filter and limit cap should work together."""
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id="active",
                    op="EQ",
                    value=True,
                ),
                OperationalRule(type="OPERATIONAL", enforce_limit=25),
            ],
        )
        rows = [{"id": "1", "name": "Alice", "active": True}]
        backend = _mock_backend(rows=rows)
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        result = await handler.handle(
            _make_query_params(
                predicates=[
                    {"fieldId": "name", "op": "EQ", "value": "test"},
                    {"fieldId": "active", "op": "EQ", "value": True},
                ],
                limit=100,
            )
        )
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["results"], rows)
        call_args = backend.execute.call_args
        intent = call_args[0][1]
        self.assertEqual(intent.limit, 25)

    async def test_mandatory_filter_missing_with_enforce_limit(self) -> None:
        """Missing mandatory filter should still raise even if limit is fine."""
        resource = _make_resource()
        policy = ResourcePolicy(
            resource_id="com.acme:test_resource",
            rules=[
                MandatoryFilterRule(
                    type="MANDATORY_FILTER",
                    field_id="active",
                    op="EQ",
                    value=True,
                ),
                OperationalRule(type="OPERATIONAL", enforce_limit=100),
            ],
        )
        backend = _mock_backend()
        handler = _make_handler(resource=resource, policy=policy, backend=backend)

        with self.assertRaises(ValidationFailedError):
            await handler.handle(_make_query_params(limit=50))
        backend.execute.assert_not_called()
