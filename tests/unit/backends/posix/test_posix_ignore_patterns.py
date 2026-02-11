"""Unit tests for POSIX backend ignore patterns."""

import tempfile
import unittest
from pathlib import Path

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, POSIXBackendConfig
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    LogicOperator,
    LookupIntent,
    PredicateGroup,
    QueryIntent,
)
from backends.posix.backend import POSIXBackend


class TestIgnorePatterns(unittest.IsolatedAsyncioTestCase):
    """Tests for ignore patterns functionality."""

    async def asyncSetUp(self) -> None:
        """Set up test backend with ignore patterns."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

        # Create test files and directories
        (self.root_path / "file.txt").write_text("content")
        (self.root_path / "file.log").write_text("log content")
        (self.root_path / ".DS_Store").write_text("mac metadata")
        (self.root_path / "data.json").write_text("{}")

        # Create subdirectory with files
        subdir = self.root_path / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("sub content")
        (subdir / "file.log").write_text("sub log")

        # Create __pycache__ directory
        pycache = self.root_path / "__pycache__"
        pycache.mkdir()
        (pycache / "module.pyc").write_text("bytecode")

        # Configure backend with ignore patterns
        config = POSIXBackendConfig(
            root_paths=[str(self.root_path)],
            ignore_patterns=["*.log", ".DS_Store", "__pycache__", "__pycache__/*", "*.pyc"],
        )
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        self.backend = POSIXBackend(definition=defn)
        await self.backend.connect()

    async def asyncTearDown(self) -> None:
        """Clean up test backend."""
        await self.backend.disconnect()
        self.tmpdir.cleanup()

    def test_should_ignore_log_files(self) -> None:
        """Test that .log files are ignored."""
        log_file = self.root_path / "file.log"
        self.assertTrue(self.backend._should_ignore(log_file, self.root_path))

    def test_should_ignore_ds_store(self) -> None:
        """Test that .DS_Store files are ignored."""
        ds_store = self.root_path / ".DS_Store"
        self.assertTrue(self.backend._should_ignore(ds_store, self.root_path))

    def test_should_ignore_pycache_contents(self) -> None:
        """Test that __pycache__ contents are ignored."""
        pyc_file = self.root_path / "__pycache__" / "module.pyc"
        self.assertTrue(self.backend._should_ignore(pyc_file, self.root_path))

    def test_should_not_ignore_regular_files(self) -> None:
        """Test that regular files are not ignored."""
        txt_file = self.root_path / "file.txt"
        self.assertFalse(self.backend._should_ignore(txt_file, self.root_path))

        json_file = self.root_path / "data.json"
        self.assertFalse(self.backend._should_ignore(json_file, self.root_path))

    def test_should_ignore_in_subdirectories(self) -> None:
        """Test that patterns work in subdirectories."""
        sub_log = self.root_path / "subdir" / "file.log"
        self.assertTrue(self.backend._should_ignore(sub_log, self.root_path))

    async def test_lookup_ignored_file_fails(self) -> None:
        """Test that LOOKUP on ignored file raises error."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="path", value="file.log"),
            projections=None,
        )

        with self.assertRaisesRegex(RuntimeError, "ignored by ignore patterns"):
            await self.backend.execute("file.log", intent)

    async def test_lookup_regular_file_succeeds(self) -> None:
        """Test that LOOKUP on regular file succeeds."""
        intent = LookupIntent(
            key=IdentityPredicate(field_id="path", value="file.txt"),
            projections=None,
        )

        result = await self.backend.execute("file.txt", intent)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["name"], "file.txt")

    async def test_query_directory_filters_ignored_files(self) -> None:
        """Test that QUERY on directory filters out ignored files."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=None,
        )

        result = await self.backend.execute(".", intent)

        # Should only see file.txt, data.json, and subdir
        # Should NOT see file.log, .DS_Store, or __pycache__
        names = {row["name"] for row in result.rows}
        self.assertIn("file.txt", names)
        self.assertIn("data.json", names)
        self.assertIn("subdir", names)
        self.assertNotIn("file.log", names)
        self.assertNotIn(".DS_Store", names)
        self.assertNotIn("__pycache__", names)

    async def test_query_subdirectory_filters_ignored_files(self) -> None:
        """Test that QUERY on subdirectory filters ignored files."""
        intent = QueryIntent(
            predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
            projections=None,
        )

        result = await self.backend.execute("subdir", intent)

        # Should only see file.txt, not file.log
        names = {row["name"] for row in result.rows}
        self.assertIn("file.txt", names)
        self.assertNotIn("file.log", names)


# =============================================================================
# Edge Cases
# =============================================================================


class TestIgnorePatternsEdgeCases(unittest.TestCase):
    """Tests for ignore patterns edge cases."""

    def setUp(self) -> None:
        """Set up test backend."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        """Clean up."""
        self.tmpdir.cleanup()

    def test_no_ignore_patterns(self) -> None:
        """Test that no patterns means nothing is ignored."""
        config = POSIXBackendConfig(root_paths=[str(self.root_path)])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        test_file = self.root_path / "file.log"
        test_file.write_text("content")

        self.assertFalse(backend._should_ignore(test_file, self.root_path))

    def test_empty_ignore_patterns(self) -> None:
        """Test that empty pattern list means nothing is ignored."""
        config = POSIXBackendConfig(root_paths=[str(self.root_path)], ignore_patterns=[])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        test_file = self.root_path / "file.log"
        test_file.write_text("content")

        self.assertFalse(backend._should_ignore(test_file, self.root_path))

    def test_wildcard_pattern(self) -> None:
        """Test wildcard patterns."""
        config = POSIXBackendConfig(root_paths=[str(self.root_path)], ignore_patterns=["test_*"])
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        test_file1 = self.root_path / "test_file.txt"
        test_file2 = self.root_path / "test_data.json"
        other_file = self.root_path / "file.txt"

        test_file1.write_text("content")
        test_file2.write_text("content")
        other_file.write_text("content")

        self.assertTrue(backend._should_ignore(test_file1, self.root_path))
        self.assertTrue(backend._should_ignore(test_file2, self.root_path))
        self.assertFalse(backend._should_ignore(other_file, self.root_path))

    def test_directory_pattern(self) -> None:
        """Test directory-specific patterns."""
        config = POSIXBackendConfig(
            root_paths=[str(self.root_path)], ignore_patterns=["node_modules/*"]
        )
        defn = BackendDefinition(id="test", type=BackendType.POSIX, config=config)
        backend = POSIXBackend(definition=defn)

        node_modules = self.root_path / "node_modules"
        node_modules.mkdir()
        module_file = node_modules / "package.json"
        module_file.write_text("{}")

        self.assertTrue(backend._should_ignore(module_file, self.root_path))
