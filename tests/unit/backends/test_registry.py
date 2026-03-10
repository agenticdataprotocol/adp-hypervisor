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

"""Tests for BackendRegistry."""

import unittest

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, RDBMSBackendConfig
from adp_hypervisor.protocol.types import Intent
from backends.base import Backend, BackendResult
from backends.registry import BackendRegistry

# =============================================================================
# Test helpers
# =============================================================================


class FakeBackend(Backend):
    """A fake backend that tracks connect/disconnect calls."""

    def __init__(self, definition: BackendDefinition, *, fail_connect: bool = False) -> None:
        super().__init__(definition)
        self.connected = False
        self.disconnected = False
        self._fail_connect = fail_connect

    async def connect(self) -> None:
        if self._fail_connect:
            raise ConnectionError(f"Cannot connect to {self.backend_id}")
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def execute(self, intent: Intent) -> BackendResult:
        return BackendResult(rows=[])


class FailDisconnectBackend(FakeBackend):
    """A backend that fails on disconnect."""

    async def disconnect(self) -> None:
        raise RuntimeError("disconnect failed")


def _make_backend(backend_id: str = "db1", *, fail_connect: bool = False) -> FakeBackend:
    defn = BackendDefinition(
        id=backend_id,
        type=BackendType.RDBMS,
        provider="postgresql",
        config=RDBMSBackendConfig(uri="postgresql://localhost/test"),
    )
    return FakeBackend(defn, fail_connect=fail_connect)


# =============================================================================
# Registration Tests
# =============================================================================


class TestRegistration(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry = BackendRegistry()
        backend = _make_backend("db1")
        registry.register(backend)
        self.assertIs(registry.get("db1"), backend)

    def test_get_nonexistent_returns_none(self) -> None:
        registry = BackendRegistry()
        self.assertIsNone(registry.get("missing"))

    def test_duplicate_registration_raises(self) -> None:
        registry = BackendRegistry()
        registry.register(_make_backend("db1"))
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(_make_backend("db1"))

    def test_list_backends(self) -> None:
        registry = BackendRegistry()
        b1 = _make_backend("db1")
        b2 = _make_backend("db2")
        registry.register(b1)
        registry.register(b2)
        backends = registry.list_backends()
        self.assertEqual(len(backends), 2)
        self.assertIn(b1, backends)
        self.assertIn(b2, backends)

    def test_len(self) -> None:
        registry = BackendRegistry()
        self.assertEqual(len(registry), 0)
        registry.register(_make_backend("db1"))
        self.assertEqual(len(registry), 1)

    def test_contains(self) -> None:
        registry = BackendRegistry()
        registry.register(_make_backend("db1"))
        self.assertIn("db1", registry)
        self.assertNotIn("db2", registry)


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_all(self) -> None:
        registry = BackendRegistry()
        b1 = _make_backend("db1")
        b2 = _make_backend("db2")
        registry.register(b1)
        registry.register(b2)

        await registry.initialize_all()

        self.assertTrue(b1.connected)
        self.assertTrue(b2.connected)

    async def test_initialize_all_propagates_error(self) -> None:
        registry = BackendRegistry()
        registry.register(_make_backend("db1"))
        registry.register(_make_backend("bad_db", fail_connect=True))

        with self.assertRaisesRegex(ConnectionError, "Cannot connect"):
            await registry.initialize_all()

    async def test_shutdown_all(self) -> None:
        registry = BackendRegistry()
        b1 = _make_backend("db1")
        b2 = _make_backend("db2")
        registry.register(b1)
        registry.register(b2)
        await registry.initialize_all()

        await registry.shutdown_all()

        self.assertTrue(b1.disconnected)
        self.assertTrue(b2.disconnected)

    async def test_shutdown_all_continues_on_error(self) -> None:
        """shutdown_all should disconnect remaining backends even if one fails."""
        registry = BackendRegistry()

        defn = BackendDefinition(
            id="fail_db",
            type=BackendType.RDBMS,
            provider="postgresql",
            config=RDBMSBackendConfig(uri="postgresql://localhost/test"),
        )
        fail_backend = FailDisconnectBackend(defn)
        good_backend = _make_backend("good_db")

        registry.register(fail_backend)
        registry.register(good_backend)

        # Should not raise
        await registry.shutdown_all()

        self.assertTrue(good_backend.disconnected)

    async def test_empty_registry_lifecycle(self) -> None:
        registry = BackendRegistry()
        await registry.initialize_all()
        await registry.shutdown_all()
