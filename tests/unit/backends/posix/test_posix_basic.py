"""Basic unit tests for POSIX backend."""

import tempfile
import unittest

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, POSIXBackendConfig
from backends.posix.backend import POSIXBackend


class TestPOSIXBackendInit(unittest.TestCase):
    """Tests for POSIX backend initialization."""

    def test_backend_id(self) -> None:
        """Test that backend_id property returns the definition ID."""
        config = POSIXBackendConfig(root_paths=[tempfile.gettempdir()])
        defn = BackendDefinition(id="posix1", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)
        self.assertEqual(backend.backend_id, "posix1")

    def test_invalid_config_type(self) -> None:
        """Test that invalid config type raises ValueError."""
        from adp_hypervisor.manifest.physical import RDBMSBackendConfig

        defn = BackendDefinition(
            id="bad",
            type=BackendType.POSIX,
            config=RDBMSBackendConfig(uri="postgresql://localhost/test"),
        )
        with self.assertRaisesRegex(ValueError, "POSIXBackend requires POSIXBackendConfig"):
            POSIXBackend(definition=defn)


class TestPOSIXBackendConnection(unittest.IsolatedAsyncioTestCase):
    """Tests for POSIX backend connection management."""

    async def test_connect_success(self) -> None:
        """Test successful connection with valid root path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = POSIXBackendConfig(root_paths=[tmpdir])
            defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
            backend = POSIXBackend(definition=defn)

            await backend.connect()
            self.assertTrue(backend._connected)
            self.assertEqual(len(backend._root_paths), 1)
            await backend.disconnect()

    async def test_connect_no_root_paths(self) -> None:
        """Test that connection fails with no root paths."""
        config = POSIXBackendConfig(root_paths=[])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        with self.assertRaisesRegex(ConnectionError, "requires at least one root path"):
            await backend.connect()
