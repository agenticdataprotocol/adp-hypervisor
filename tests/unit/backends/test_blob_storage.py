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

    async def test_connect_rejects_symlink_root_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real"
            real_dir.mkdir()
            symlink_dir = Path(tmpdir) / "link"
            symlink_dir.symlink_to(real_dir)

            backend = LocalFSBackend(_make_definition(uri=str(symlink_dir), allow_symlinks=False))
            with self.assertRaises(ConnectionError, msg="symlink"):
                await backend.connect()

    async def test_connect_allows_symlink_root_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            real_dir = Path(tmpdir) / "real"
            real_dir.mkdir()
            symlink_dir = Path(tmpdir) / "link"
            symlink_dir.symlink_to(real_dir)

            backend = LocalFSBackend(_make_definition(uri=str(symlink_dir), allow_symlinks=True))
            await backend.connect()
            self.assertTrue(backend._connected)
            await backend.disconnect()


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
                key=IdentityPredicate(field_id="path", op="EQ", value="hello.txt"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            row = result.rows[0]
            self.assertEqual(row["path"], "hello.txt")
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
                key=IdentityPredicate(field_id="path", op="EQ", value="test.png"),
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
                key=IdentityPredicate(field_id="path", op="EQ", value="missing.txt"),
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
                key=IdentityPredicate(field_id="path", op="EQ", value="test.txt"),
                projections=["path", "content"],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            row = result.rows[0]
            self.assertIn("path", row)
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
                with self.assertRaises(RuntimeError, msg="field_id must be 'path'"):
                    await backend.execute(intent)

    async def test_lookup_binary_pdf_returns_base64(self) -> None:
        """LOOKUP a file with application/pdf MIME type must return base64."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake pdf content")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="doc.pdf"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["content_encoding"], "base64")
            decoded = base64.b64decode(result.rows[0]["content"])
            self.assertEqual(decoded, b"%PDF-1.4 fake pdf content")

    async def test_lookup_non_utf8_falls_back_to_base64(self) -> None:
        """LOOKUP a file with non-UTF-8 bytes must fall back to base64."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            raw_bytes = b"\x80\x81\x82 not valid utf-8"
            (source_dir / "data.bin").write_bytes(raw_bytes)

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="data.bin"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["content_encoding"], "base64")
            decoded = base64.b64decode(result.rows[0]["content"])
            self.assertEqual(decoded, raw_bytes)


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
            names = {r["path"] for r in result.rows}
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
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="match.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["path"], "match.txt")

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
            self.assertEqual(result.rows[0]["path"], "file.txt")

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

            names = {r["path"] for r in result.rows}
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
                projections=["path", "size"],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            row = result.rows[0]
            self.assertIn("path", row)
            self.assertIn("size", row)
            self.assertNotIn("last_modified", row)

    async def test_query_with_in_predicate(self) -> None:
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
                        Predicate(
                            field_id="path",
                            op=PredicateOperator.IN,
                            value=["a.txt", "b.txt"],
                        ),
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            names = {r["path"] for r in result.rows}
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
                                Predicate(field_id="path", op=PredicateOperator.EQ, value="a.txt"),
                                Predicate(field_id="path", op=PredicateOperator.EQ, value="b.log"),
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

            names = {r["path"] for r in result.rows}
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
                        Predicate(field_id="path", op=PredicateOperator.SIMILAR, value="file"),
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
                projections=["path"],
                order_by=[SortOrder(field_id="size", direction="DESC")],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.rows[0]["path"], "large.txt")
            self.assertNotIn("size", result.rows[0])

    async def test_predicate_int_vs_float_comparison(self) -> None:
        """Numeric int vs float comparisons must not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "big.txt").write_text("x" * 2000)
            (source_dir / "small.txt").write_text("x")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="size", op=PredicateOperator.GT, value=1000.0),
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["path"], "big.txt")

    async def test_query_limit_without_order_stops_early(self) -> None:
        """QUERY with limit and no order_by should stop collecting early."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            for i in range(10):
                (source_dir / f"file_{i:02d}.txt").write_text(f"content {i}")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                limit=3,
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 3)
            # Sorted alphabetically, first 3 files
            self.assertEqual(result.rows[0]["path"], "file_00.txt")
            self.assertEqual(result.rows[2]["path"], "file_02.txt")

    async def test_query_projections_applied_in_loop(self) -> None:
        """QUERY projections without order_by should be applied eagerly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "a.txt").write_text("aaa")
            (source_dir / "b.txt").write_text("bbb")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(predicates=[], op=LogicOperator.AND),
                projections=["path", "size"],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 2)
            for row in result.rows:
                self.assertEqual(set(row.keys()), {"path", "size"})
                self.assertNotIn("content_type", row)


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
                payload=[{"path": "new.txt", "content": "hello"}],
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
                payload=[{"path": "subdir", "is_directory": True}],
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
                payload=[{"path": "img.png", "content": encoded, "content_encoding": "base64"}],
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
                payload=[{"path": "existing.txt", "content": "new"}],
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
                    {"path": "a.txt", "content": "aaa"},
                    {"path": "b.txt", "content": "bbb"},
                ],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["affected"], 2)
            self.assertTrue((source_dir / "a.txt").exists())
            self.assertTrue((source_dir / "b.txt").exists())

    async def test_ingest_is_directory_non_bool_raises(self) -> None:
        """INGEST must reject non-boolean is_directory values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"path": "subdir", "is_directory": "true"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="'is_directory' must be a boolean"):
                    await backend.execute(intent)


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
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="target.txt")
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
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="missing.txt")
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
                with self.assertRaises(RuntimeError, msg="field_id='path'"):
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
                key=IdentityPredicate(field_id="path", op="EQ", value="../etc/passwd"),
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

    async def test_intermediate_symlink_rejected(self) -> None:
        """Symlinks in intermediate path components must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            hidden = Path(tmpdir) / "hidden"
            hidden.mkdir()
            (hidden / "secret.txt").write_text("sensitive")
            (source_dir / "link").symlink_to(hidden)

            backend = LocalFSBackend(_make_definition(uri=tmpdir, allow_symlinks=False))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="link/secret.txt"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="Symlinks are not allowed"):
                    await backend.execute(intent)

    async def test_symlink_escapes_source_dir_rejected(self) -> None:
        """Symlinks pointing outside source_dir are rejected even within root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_a = Path(tmpdir) / "resource_a"
            source_a.mkdir()
            source_b = Path(tmpdir) / "resource_b"
            source_b.mkdir()
            (source_b / "private.txt").write_text("private data")
            (source_a / "escape").symlink_to(source_b)

            backend = LocalFSBackend(_make_definition(uri=tmpdir, allow_symlinks=True))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="escape/private.txt"),
            )
            mock_index = _mock_manifest_index("resource_a")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="escapes source directory"):
                    await backend.execute(intent)

    async def test_ignore_patterns_applied_to_lookup(self) -> None:
        """LOOKUP on an ignored file must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "file.tmp").write_text("temp")

            backend = LocalFSBackend(_make_definition(uri=tmpdir, ignore_patterns=["*.tmp"]))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="file.tmp"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="ignore pattern"):
                    await backend.execute(intent)

    async def test_ignore_patterns_applied_to_ingest(self) -> None:
        """INGEST to an ignored path must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir, ignore_patterns=["*.tmp"]))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"path": "new.tmp", "content": "data"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="ignore pattern"):
                    await backend.execute(intent)

    async def test_ignore_patterns_applied_to_revise(self) -> None:
        """REVISE on an ignored file must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "secret.tmp").write_text("old")

            backend = LocalFSBackend(_make_definition(uri=tmpdir, ignore_patterns=["*.tmp"]))
            await backend.connect()

            intent = ReviseIntent(
                intent_class="REVISE",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="secret.tmp")
                    ],
                    op=LogicOperator.AND,
                ),
                payload={"content": "new"},
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="ignore pattern"):
                    await backend.execute(intent)


# =============================================================================
# TestLocalFSBackendSubdirectory
# =============================================================================


class TestLocalFSBackendSubdirectory(unittest.IsolatedAsyncioTestCase):
    """Tests for subdirectory operations via the ``path`` field."""

    async def test_query_subdir_lists_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            sub = source_dir / "reports"
            sub.mkdir()
            (sub / "jan.csv").write_text("jan")
            (sub / "feb.csv").write_text("feb")
            (source_dir / "root.txt").write_text("root")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="reports")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"reports/feb.csv", "reports/jan.csv"})

    async def test_query_path_eq_file_returns_single(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            sub = source_dir / "reports"
            sub.mkdir()
            (sub / "jan.csv").write_text("jan-data")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(
                            field_id="path",
                            op=PredicateOperator.EQ,
                            value="reports/jan.csv",
                        )
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["path"], "reports/jan.csv")

    async def test_query_path_eq_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(
                            field_id="path",
                            op=PredicateOperator.EQ,
                            value="no_such_dir",
                        )
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="Path not found"):
                    await backend.execute(intent)

    async def test_query_multiple_path_predicates_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="a"),
                        Predicate(field_id="path", op=PredicateOperator.EQ, value="b"),
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="one 'path' predicate"):
                    await backend.execute(intent)

    async def test_lookup_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            sub = source_dir / "2024"
            sub.mkdir()
            (sub / "report.txt").write_text("content")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="2024/report.txt"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.rows[0]["path"], "2024/report.txt")
            self.assertEqual(result.rows[0]["content"], "content")

    async def test_ingest_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"path": "2024/new.txt", "content": "hello"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertTrue((source_dir / "2024" / "new.txt").exists())
            self.assertEqual((source_dir / "2024" / "new.txt").read_text(), "hello")

    async def test_revise_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            sub = source_dir / "docs"
            sub.mkdir()
            (sub / "readme.md").write_text("old")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = ReviseIntent(
                intent_class="REVISE",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(
                            field_id="path",
                            op=PredicateOperator.EQ,
                            value="docs/readme.md",
                        )
                    ],
                    op=LogicOperator.AND,
                ),
                payload={"content": "new"},
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            self.assertEqual(result.metadata["status"], "SUCCESS")
            self.assertEqual((sub / "readme.md").read_text(), "new")

    async def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = LookupIntent(
                intent_class="LOOKUP",
                resource_id=_RID,
                key=IdentityPredicate(field_id="path", op="EQ", value="sub/../../../etc/passwd"),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="traversal"):
                    await backend.execute(intent)

    async def test_absolute_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = IngestIntent(
                intent_class="INGEST",
                resource_id=_RID,
                payload=[{"path": "/etc/passwd", "content": "bad"}],
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                with self.assertRaises(RuntimeError, msg="Absolute paths"):
                    await backend.execute(intent)


# =============================================================================
# TestLocalFSBackendPathLike
# =============================================================================


class TestLocalFSBackendPathLike(unittest.IsolatedAsyncioTestCase):
    """Tests for LIKE / ILIKE predicates on the ``path`` field."""

    async def test_query_path_like_top_level_extension_filter(self) -> None:
        """path LIKE '%.txt' filters files by extension at the top level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "readme.txt").write_text("r")
            (source_dir / "notes.md").write_text("n")
            (source_dir / "config.txt").write_text("c")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="%.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"readme.txt", "config.txt"})

    async def test_query_path_like_recursive_subdir_prefix(self) -> None:
        """path LIKE 'docs/%' returns all entries under docs/ recursively."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            docs = source_dir / "docs"
            docs.mkdir()
            (docs / "intro.txt").write_text("i")
            (docs / "guide.md").write_text("g")
            (source_dir / "root.txt").write_text("r")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="docs/%")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"docs/intro.txt", "docs/guide.md"})

    async def test_query_path_like_deep_nested(self) -> None:
        """path LIKE 'a/b/%.csv' matches files at arbitrary depth."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            deep = source_dir / "a" / "b"
            deep.mkdir(parents=True)
            (deep / "report.csv").write_text("data")
            (deep / "summary.txt").write_text("txt")
            (source_dir / "a" / "other.csv").write_text("other")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="a/b/%.csv")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"a/b/report.csv"})

    async def test_query_path_ilike_case_insensitive(self) -> None:
        """path ILIKE '%.TXT' matches regardless of filename case."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "readme.txt").write_text("r")
            (source_dir / "notes.md").write_text("n")

            backend = LocalFSBackend(_make_definition(uri=tmpdir))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.ILIKE, value="%.TXT")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"readme.txt"})

    async def test_query_path_like_respects_ignore_patterns(self) -> None:
        """Ignored directories are not traversed during recursive path LIKE walk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "keep").mkdir()
            (source_dir / "keep" / "file.txt").write_text("keep")
            (source_dir / ".hidden").mkdir()
            (source_dir / ".hidden" / "secret.txt").write_text("ignore")

            backend = LocalFSBackend(_make_definition(uri=tmpdir, ignore_patterns=[".hidden"]))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="%.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"keep/file.txt"})

    async def test_query_path_like_symlinked_dir_not_followed(self) -> None:
        """Symlinked directories are not followed during recursive walk.

        The symlinked directory itself appears as an entry but its contents
        are not traversed, preventing directory escape.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            external_dir = Path(tmpdir) / "external"
            external_dir.mkdir()
            (external_dir / "secret.txt").write_text("secret")

            # symlink inside source pointing to external directory
            (source_dir / "link").symlink_to(external_dir)
            (source_dir / "real.txt").write_text("real")

            backend = LocalFSBackend(_make_definition(uri=tmpdir, allow_symlinks=True))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="%.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            # secret.txt inside the symlinked dir must not appear
            self.assertNotIn("link/secret.txt", paths)
            self.assertIn("real.txt", paths)

    async def test_query_path_like_symlink_loop_does_not_hang(self) -> None:
        """A self-referential symlink inside source does not cause infinite recursion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "data"
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("hello")
            # Symlink pointing back to source_dir itself
            (source_dir / "loop").symlink_to(source_dir)

            backend = LocalFSBackend(_make_definition(uri=tmpdir, allow_symlinks=True))
            await backend.connect()

            intent = QueryIntent(
                intent_class="QUERY",
                resource_id=_RID,
                predicates=PredicateGroup(
                    predicates=[
                        Predicate(field_id="path", op=PredicateOperator.LIKE, value="%.txt")
                    ],
                    op=LogicOperator.AND,
                ),
            )
            mock_index = _mock_manifest_index("data")
            with patch(_MANIFEST_INDEX_PATH, return_value=mock_index):
                result = await backend.execute(intent)

            paths = {r["path"] for r in result.rows}
            self.assertEqual(paths, {"file.txt"})
