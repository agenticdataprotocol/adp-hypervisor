"""Basic unit tests for POSIX backend."""

import tempfile
import unittest
from pathlib import Path

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, POSIXBackendConfig
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    IngestIntent,
    LogicOperator,
    LookupIntent,
    PredicateGroup,
    QueryIntent,
    ReviseIntent,
)
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

    async def test_connect_nonexistent_path(self) -> None:
        """Test that connection fails with non-existent root path."""
        config = POSIXBackendConfig(root_paths=["/nonexistent/path"])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        with self.assertRaisesRegex(ConnectionError, "Root path does not exist"):
            await backend.connect()

    async def test_connect_not_a_directory(self) -> None:
        """Test that connection fails when root path is a file."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            config = POSIXBackendConfig(root_paths=[tmpfile.name])
            defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
            backend = POSIXBackend(definition=defn)

            with self.assertRaisesRegex(ConnectionError, "Root path is not a directory"):
                await backend.connect()


class TestPOSIXBackendLookup(unittest.IsolatedAsyncioTestCase):
    """Tests for LOOKUP intent operations."""

    async def asyncSetUp(self) -> None:
        """Set up test backend with temporary directory."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

        # Create test files and directories
        (self.root_path / "file.txt").write_text("Hello, World!")
        subdir = self.root_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content")

        config = POSIXBackendConfig(root_paths=[str(self.root_path)])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        self.backend = POSIXBackend(definition=defn)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Clean up test backend."""
        await self.backend.disconnect()
        self.tmpdir.cleanup()

    async def test_lookup_directory_reads_file(self) -> None:
        """Test LOOKUP on directory reads file content."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="file_name", value="file.txt"),
            projections=None,
        )

        result = await self.backend.execute(".", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["file_name"], "file.txt")
        self.assertEqual(result.rows[0]["content"], "Hello, World!")
        self.assertEqual(result.rows[0]["content_format"], "raw")

    async def test_lookup_directory_nested_file(self) -> None:
        """Test LOOKUP reads file in subdirectory."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="file_name", value="nested.txt"),
            projections=None,
        )

        result = await self.backend.execute("subdir", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["file_name"], "nested.txt")
        self.assertEqual(result.rows[0]["content"], "Nested content")

    async def test_lookup_directory_missing_file_name(self) -> None:
        """Test LOOKUP fails without file_name key."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="path", value="file.txt"),
            projections=None,
        )

        with self.assertRaisesRegex(RuntimeError, "requires 'file_name' key field_id"):
            await self.backend.execute(".", intent)

    async def test_lookup_file_not_supported(self) -> None:
        """Test LOOKUP on file raises error."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="file_name", value="file.txt"),
            projections=None,
        )

        with self.assertRaisesRegex(RuntimeError, "LOOKUP intent is not supported for files"):
            await self.backend.execute("file.txt", intent)

    async def test_lookup_nonexistent_file(self) -> None:
        """Test LOOKUP on non-existent file raises error."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="file_name", value="nonexistent.txt"),
            projections=None,
        )

        with self.assertRaisesRegex(RuntimeError, "File not found"):
            await self.backend.execute(".", intent)


class TestPOSIXBackendQuery(unittest.IsolatedAsyncioTestCase):
    """Tests for QUERY intent operations."""

    async def asyncSetUp(self) -> None:
        """Set up test backend with temporary directory."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

        # Create test files and directories
        (self.root_path / "file1.txt").write_text("Content 1")
        (self.root_path / "file2.txt").write_text("Content 2")
        subdir = self.root_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested")

        config = POSIXBackendConfig(root_paths=[str(self.root_path)])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        self.backend = POSIXBackend(definition=defn)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Clean up test backend."""
        await self.backend.disconnect()
        self.tmpdir.cleanup()

    async def test_query_directory_lists_files(self) -> None:
        """Test QUERY on directory lists files."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=None,
        )

        result = await self.backend.execute(".", intent)
        self.assertEqual(len(result.rows), 3)  # file1.txt, file2.txt, subdir
        names = {row["name"] for row in result.rows}
        self.assertEqual(names, {"file1.txt", "file2.txt", "subdir"})

    async def test_query_file_returns_content(self) -> None:
        """Test QUERY on file returns content."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=["name", "content"],
        )

        result = await self.backend.execute("file1.txt", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "file1.txt")
        self.assertEqual(result.rows[0]["content"], "Content 1")

    async def test_query_directory_with_limit(self) -> None:
        """Test QUERY on directory with limit."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=None,
            limit=2,
        )

        result = await self.backend.execute(".", intent)
        self.assertEqual(len(result.rows), 2)

    async def test_query_nonexistent_resource(self) -> None:
        """Test QUERY on non-existent resource raises error."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=None,
        )

        with self.assertRaisesRegex(RuntimeError, "Resource not found"):
            await self.backend.execute("nonexistent.txt", intent)


class TestPOSIXBackendIngest(unittest.IsolatedAsyncioTestCase):
    """Tests for INGEST intent operations."""

    async def asyncSetUp(self) -> None:
        """Set up test backend with temporary directory."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

        config = POSIXBackendConfig(root_paths=[str(self.root_path)])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        self.backend = POSIXBackend(definition=defn)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Clean up test backend."""
        await self.backend.disconnect()
        self.tmpdir.cleanup()

    async def test_ingest_create_file(self) -> None:
        """Test INGEST creates new file."""
        intent = IngestIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload=[{"content": "New file content", "content_format": "raw"}],
        )

        result = await self.backend.execute("newfile.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")
        self.assertEqual(result.metadata["affected"], 1)

        # Verify file was created
        content = (self.root_path / "newfile.txt").read_text()
        self.assertEqual(content, "New file content")

    async def test_ingest_create_directory(self) -> None:
        """Test INGEST creates new directory."""
        intent = IngestIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload=[{"object_type": "directory"}],
        )

        result = await self.backend.execute("newdir", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")
        self.assertEqual(result.metadata["affected"], 1)

        # Verify directory was created
        self.assertTrue((self.root_path / "newdir").is_dir())

    async def test_ingest_file_already_exists(self) -> None:
        """Test INGEST fails when file exists without overwrite flag."""
        (self.root_path / "existing.txt").write_text("Existing content")

        intent = IngestIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload=[{"content": "New content", "content_format": "raw"}],
        )

        with self.assertRaisesRegex(RuntimeError, "Target already exists"):
            await self.backend.execute("existing.txt", intent)

    async def test_ingest_overwrite_existing(self) -> None:
        """Test INGEST overwrites file with overwrite_existing flag."""
        (self.root_path / "existing.txt").write_text("Old content")

        intent = IngestIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload=[
                {
                    "content": "New content",
                    "content_format": "raw",
                    "overwrite_existing": True,
                }
            ],
        )

        result = await self.backend.execute("existing.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")

        # Verify content was overwritten
        content = (self.root_path / "existing.txt").read_text()
        self.assertEqual(content, "New content")


class TestPOSIXBackendRevise(unittest.IsolatedAsyncioTestCase):
    """Tests for REVISE intent operations."""

    async def asyncSetUp(self) -> None:
        """Set up test backend with temporary directory."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

        # Create test file
        (self.root_path / "test.txt").write_text("Original content")

        config = POSIXBackendConfig(root_paths=[str(self.root_path)])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        self.backend = POSIXBackend(definition=defn)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Clean up test backend."""
        await self.backend.disconnect()
        self.tmpdir.cleanup()

    async def test_revise_overwrite_file(self) -> None:
        """Test REVISE overwrites file content."""
        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={
                "function": {"name": "overwrite", "args": {}},
                "content": "Revised content",
                "content_format": "raw",
            },
        )

        result = await self.backend.execute("test.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")

        # Verify content was revised
        content = (self.root_path / "test.txt").read_text()
        self.assertEqual(content, "Revised content")

    async def test_revise_append_to_file(self) -> None:
        """Test REVISE appends to file content."""
        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={
                "function": {"name": "append", "args": {}},
                "content": "\nAppended text",
                "content_format": "raw",
            },
        )

        result = await self.backend.execute("test.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")

        # Verify content was appended
        content = (self.root_path / "test.txt").read_text()
        self.assertEqual(content, "Original content\nAppended text")

    async def test_revise_rename_file(self) -> None:
        """Test REVISE renames file."""
        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={"function": {"name": "rename", "args": {"new_name": "renamed.txt"}}},
        )

        result = await self.backend.execute("test.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")

        # Verify file was renamed
        self.assertFalse((self.root_path / "test.txt").exists())
        self.assertTrue((self.root_path / "renamed.txt").exists())
        self.assertEqual((self.root_path / "renamed.txt").read_text(), "Original content")

    async def test_revise_delete_file(self) -> None:
        """Test REVISE deletes file."""
        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={"function": {"name": "delete", "args": {}}},
        )

        result = await self.backend.execute("test.txt", intent)
        self.assertEqual(result.metadata["status"], "SUCCESS")

        # Verify file was deleted
        self.assertFalse((self.root_path / "test.txt").exists())

    async def test_revise_directory_not_supported(self) -> None:
        """Test REVISE on directory raises error."""
        (self.root_path / "subdir").mkdir()

        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={"function": {"name": "delete", "args": {}}},
        )

        with self.assertRaisesRegex(RuntimeError, "REVISE intent is not supported for directories"):
            await self.backend.execute("subdir", intent)

    async def test_revise_nonexistent_file(self) -> None:
        """Test REVISE on non-existent file raises error."""
        intent = ReviseIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            payload={"content": "New content", "content_format": "raw"},
        )

        with self.assertRaisesRegex(RuntimeError, "Resource not found"):
            await self.backend.execute("nonexistent.txt", intent)
