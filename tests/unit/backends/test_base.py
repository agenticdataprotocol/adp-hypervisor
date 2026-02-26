"""Tests for Backend abstract base class."""

import unittest
from typing import Any
from unittest.mock import MagicMock

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, RDBMSBackendConfig
from adp_hypervisor.protocol.types import (
    Intent,
)
from backends.base import Backend, BackendResult

# =============================================================================
# Concrete test implementation
# =============================================================================


class StubBackend(Backend):
    """Minimal concrete backend for testing the ABC contract."""

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def execute(self, source: str, intent: Intent) -> BackendResult:
        return BackendResult(rows=[{"id": 1, "name": "test"}])


def _make_definition(backend_id: str = "test_db") -> BackendDefinition:
    return BackendDefinition(
        id=backend_id,
        type=BackendType.RDBMS,
        provider="postgresql",
        config=RDBMSBackendConfig(uri="postgresql://localhost/test"),
    )


# =============================================================================
# BackendResult Tests
# =============================================================================


class TestBackendResult(unittest.TestCase):
    def test_basic_result(self) -> None:
        result = BackendResult(rows=[{"id": 1}])
        self.assertEqual(result.rows, [{"id": 1}])
        self.assertEqual(result.metadata, {})

    def test_result_with_metadata(self) -> None:
        result = BackendResult(
            rows=[{"id": 1}],
            metadata={"duration_ms": 42, "source_system": "postgres"},
        )
        self.assertEqual(result.metadata["duration_ms"], 42)

    def test_empty_result(self) -> None:
        result = BackendResult(rows=[])
        self.assertEqual(result.rows, [])


# =============================================================================
# Backend ABC Tests
# =============================================================================


class TestBackendABC(unittest.TestCase):
    def test_cannot_instantiate_abc(self) -> None:
        with self.assertRaises(TypeError):
            Backend(definition=_make_definition())  # type: ignore[abstract]

    def test_backend_id_from_definition(self) -> None:
        backend = StubBackend(definition=_make_definition("my_db"))
        self.assertEqual(backend.backend_id, "my_db")

    def test_definition_property(self) -> None:
        defn = _make_definition("finance_sql")
        backend = StubBackend(definition=defn)
        self.assertIs(backend.definition, defn)
        self.assertEqual(backend.definition.type, BackendType.RDBMS)


# =============================================================================
# Stub Backend Lifecycle Tests
# =============================================================================


class TestStubBackendLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.backend = StubBackend(definition=_make_definition())

    async def test_connect(self) -> None:
        self.assertFalse(self.backend.connected)
        await self.backend.connect()
        self.assertTrue(self.backend.connected)

    async def test_disconnect(self) -> None:
        await self.backend.connect()
        await self.backend.disconnect()
        self.assertTrue(self.backend.disconnected)

    async def test_execute(self) -> None:
        mock_intent: Any = MagicMock()
        result = await self.backend.execute("users", mock_intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "test")
