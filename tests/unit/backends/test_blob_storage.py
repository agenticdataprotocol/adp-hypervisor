"""Unit tests for the local filesystem backend (BLOB_STORAGE + local provider)."""

import base64
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    BlobStorageBackendConfig,
    RDBMSBackendConfig,
)
from adp_hypervisor.protocol.types import (
    IdentityPredicate,
    IngestIntent,
    LogicOperator,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
)
from backends.blob_storage.local import LocalFSBackend

# =============================================================================
# Test helpers
# =============================================================================

_RID = "com.acme:test"

_MANIFEST_INDEX_PATH = "backends.blob_storage.local.get_global_manifest_index"


def _make_definition(uri: str = "/tmp/blob-test", **kwargs: object) -> BackendDefinition:
    config_kwargs: dict[str, Any] = {"uri": uri}
    config_kwargs.update(kwargs)
    return BackendDefinition(
        id="test_blob",
        type=BackendType.BLOB_STORAGE,
        provider="local",
        config=BlobStorageBackendConfig(**config_kwargs),
    )


def _mock_manifest_index(source: str) -> MagicMock:
    """Build a mock ManifestIndex whose get_resource returns the given source."""
    resource = MagicMock()
    resource.source_definition.source = source
    resource.resource_id = _RID
    index = MagicMock()
    index.get_resource.return_value = resource
    return index


# =============================================================================
# TestLocalFSBackendConstructor
# =============================================================================


class TestLocalFSBackendConstructor(unittest.TestCase):
    def test_valid_config(self) -> None:
        defn = _make_definition()
        backend = LocalFSBackend(defn)
        self.assertEqual(backend.backend_id, "test_blob")

    def test_wrong_config_type(self) -> None:
        defn = BackendDefinition(
            id="bad",
            type=BackendType.RDBMS,
            provider="postgresql",
            config=RDBMSBackendConfig(uri="postgresql://localhost/db"),
        )
        with self.assertRaises(ValueError):
            LocalFSBackend(defn)


# =============================================================================
# TestLocalFSBackendConnect
# =============================================================================


class TestLocalFSBackendConnect(unittest.IsolatedAsyncioTestCase):
    async def test_connect_valid_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()
            self.assertTrue(backend._connected)
            await backend.disconnect()

    async def test_connect_missing_path(self) -> None:
        backend = LocalFSBackend(_make_definition(uri="/nonexistent/path"))
        with self.assertRaises(ConnectionError):
            await backend.connect()

    async def test_connect_not_a_directory(self) -> None:
        with tempfile.NamedTemporaryFile() as tmpfile:
            backend = LocalFSBackend(_make_definition(uri=tmpfile.name))
            with self.assertRaises(ConnectionError):
                await backend.connect()

    async def test_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()
            await backend.disconnect()
            self.assertFalse(backend._connected)


# =============================================================================
# TestLocalFSBackendLookup
# =============================================================================


class TestLocalFSBackendLookup(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "hello.txt").write_text("hello world")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="name", op="EQ", value="hello.txt"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            row = result.rows[0]
            self.assertEqual(row["name"], "hello.txt")
            self.assertEqual(row["content"], "hello world")
            self.assertEqual(row["content_encoding"], "utf-8")
            self.assertFalse(row["is_directory"])
            self.assertIn("size", row)
            self.assertIn("last_modified", row)
            self.assertIn("created_at", row)

    async def test_lookup_binary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "images"
            source_dir.mkdir()
            (source_dir / "test.png").write_bytes(b"\x89PNG\r\n")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="name", op="EQ", value="test.png"),
            )
            mock_index = _mock_manifest_index("images")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            row = result.rows[0]
            self.assertEqual(row["content_encoding"], "base64")
            decoded = base64.b64decode(row["content"])
            self.assertEqual(decoded, b"\x89PNG\r\n")

    async def test_lookup_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="name", op="EQ", value="missing.txt"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="File not found"):
                    await backend.execute(intent)

    async def test_lookup_with_projections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "test.txt").write_text("content")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="name", op="EQ", value="test.txt"),
                projections=["name", "content"],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            row = result.rows[0]
            self.assertIn("name", row)
            self.assertIn("content", row)
            self.assertNotIn("size", row)

    async def test_lookup_wrong_key_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="id", op="EQ", value="test"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="field_id must be 'name'"):
                    await backend.execute(intent)


# =============================================================================
# TestLocalFSBackendQuery
# =============================================================================


class TestLocalFSBackendQuery(unittest.IsolatedAsyncioTestCase):
    async def test_query_list_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "a.txt").write_text("aaa")
            (source_dir / "b.txt").write_text("bbb")
            (source_dir / "subdir").mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 3)
            names = {r["name"] for r in result.rows}
            self.assertEqual(names, {"a.txt", "b.txt", "subdir"})
            # Content should not be in QUERY results
            for row in result.rows:
                self.assertNotIn("content", row)

    async def test_query_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            for i in range(5):
                (source_dir / f"file{i}.txt").write_text(f"content{i}")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                limit=2,
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 2)

    async def test_query_with_name_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "match.txt").write_text("yes")
            (source_dir / "other.txt").write_text("no")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="name", op=PredicateOperator.EQ, value="match.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["name"], "match.txt")

    async def test_query_with_is_directory_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("text")
            (source_dir / "subdir").mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="is_directory", op=PredicateOperator.EQ, value=False)
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["name"], "file.txt")

    async def test_query_with_ignore_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "keep.txt").write_text("keep")
            (source_dir / "ignore.tmp").write_text("ignore")

            backend = LocalFSBackend(_make_definition(uri=tmpdir, ignore_patterns=["*.tmp"]))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            names = {r["name"] for r in result.rows}
            self.assertIn("keep.txt", names)
            self.assertNotIn("ignore.tmp", names)

    async def test_query_with_projections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("hello")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                projections=["name", "size"],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            row = result.rows[0]
            self.assertIn("name", row)
            self.assertIn("size", row)
            self.assertNotIn("last_modified", row)

    async def test_query_with_or_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "a.txt").write_text("aaa")
            (source_dir / "b.txt").write_text("bbb")
            (source_dir / "c.txt").write_text("ccc")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="name", op=PredicateOperator.EQ, value="a.txt"),
                        Predicate(field_id="name", op=PredicateOperator.EQ, value="b.txt"),
                    ],
                    op=LogicOperator.OR,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            names = {r["name"] for r in result.rows}
            self.assertEqual(names, {"a.txt", "b.txt"})

    async def test_query_with_nested_predicate_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "a.txt").write_text("aaa")
            (source_dir / "b.log").write_text("bbb")
            sub = source_dir / "subdir"
            sub.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="is_directory", op=PredicateOperator.EQ, value=False),
                        PredicateGroup(
                            predicates=[
                                Predicate(field_id="name", op=PredicateOperator.EQ, value="a.txt"),
                                Predicate(field_id="name", op=PredicateOperator.EQ, value="b.log"),
                            ],
                            op=LogicOperator.OR,
                        ),
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            names = {r["name"] for r in result.rows}
            self.assertEqual(names, {"a.txt", "b.log"})

    async def test_query_unsupported_operator_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("hello")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="name", op=PredicateOperator.SIMILAR, value="file"),
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="Unsupported predicate operator"):
                    await backend.execute(intent)

    async def test_query_projections_applied_after_sort(self) -> None:
        """Projections must not interfere with order_by on non-projected fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "small.txt").write_text("x")
            (source_dir / "large.txt").write_text("x" * 1000)

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            from adp_hypervisor.protocol.types import SortOrder

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                projections=["name"],
                order_by=[SortOrder(field_id="size", direction="DESC")],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.rows[0]["name"], "large.txt")
            self.assertNotIn("size", result.rows[0])


# =============================================================================
# TestLocalFSBackendIngest
# =============================================================================


class TestLocalFSBackendIngest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_create_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"name": "new.txt", "content": "hello"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertEqual(result.metadata["affected"], 1)
            self.assertTrue((source_dir / "new.txt").exists())
            self.assertEqual((source_dir / "new.txt").read_text(), "hello")

    async def test_ingest_create_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"name": "subdir", "is_directory": True}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertTrue((source_dir / "subdir").is_dir())

    async def test_ingest_base64_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            raw_data = b"\x89PNG\r\n"
            encoded = base64.b64encode(raw_data).decode("ascii")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"name": "img.png", "content": encoded, "content_encoding": "base64"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertEqual((source_dir / "img.png").read_bytes(), raw_data)

    async def test_ingest_duplicate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "existing.txt").write_text("old")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"name": "existing.txt", "content": "new"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="already exists"):
                    await backend.execute(intent)

    async def test_ingest_multiple_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[
                    {"name": "a.txt", "content": "aaa"},
                    {"name": "b.txt", "content": "bbb"},
                ],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["affected"], 2)
            self.assertTrue((source_dir / "a.txt").exists())
            self.assertTrue((source_dir / "b.txt").exists())


# =============================================================================
# TestLocalFSBackendRevise
# =============================================================================


class TestLocalFSBackendRevise(unittest.IsolatedAsyncioTestCase):
    async def test_revise_overwrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "target.txt").write_text("old content")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = ReviseIntent(
                intent_class="REVISE",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="name", op=PredicateOperator.EQ, value="target.txt")
                    ],
                    op=LogicOperator.AND,
                ),
                payload={"content": "new content"},
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertEqual((source_dir / "target.txt").read_text(), "new content")

    async def test_revise_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = ReviseIntent(
                intent_class="REVISE",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="name", op=PredicateOperator.EQ, value="missing.txt")
                    ],
                    op=LogicOperator.AND,
                ),
                payload={"content": "data"},
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="File not found"):
                    await backend.execute(intent)

    async def test_revise_no_name_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = ReviseIntent(
                intent_class="REVISE",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                payload={"content": "data"},
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="field_id='name'"):
                    await backend.execute(intent)


# =============================================================================
# TestLocalFSBackendAutoCreateSource
# =============================================================================


class TestLocalFSBackendAutoCreateSource(unittest.IsolatedAsyncioTestCase):
    async def test_auto_create_source_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(_make_definition(uri=tmpdir, auto_create_source=True))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
            )
            mock_index = _mock_manifest_index("auto_created_dir")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.rows, [])
            self.assertTrue((Path(tmpdir) / "auto_created_dir").is_dir())

    async def test_auto_create_source_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(_make_definition(uri=tmpdir, auto_create_source=False))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
            )
            mock_index = _mock_manifest_index("nonexistent_dir")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="does not exist"):
                    await backend.execute(intent)


# =============================================================================
# TestLocalFSBackendSecurity
# =============================================================================


class TestLocalFSBackendSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_path_traversal_in_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
            )
            mock_index = _mock_manifest_index("../escape")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(ValueError, msg="traversal"):
                    await backend.execute(intent)

    async def test_path_separator_in_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="name", op="EQ", value="../etc/passwd"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError):
                    await backend.execute(intent)

    async def test_not_connected_raises(self) -> None:
        backend = LocalFSBackend(_make_definition())
        intent = QueryIntent(
            intent_class="QUERY",
            resource_id=_RID,
            predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
        )
        with self.assertRaises(RuntimeError, msg="not connected"):
            await backend.execute(intent)
