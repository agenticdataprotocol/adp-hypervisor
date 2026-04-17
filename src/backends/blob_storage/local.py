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

"""
Local Filesystem Backend for BLOB_STORAGE.

Provides ADP Intent-based access to POSIX-compliant local file systems.
Each resource maps to a directory; files in the directory are queryable
entries with convention-based metadata fields.
"""

import base64
import fnmatch
import logging
import mimetypes
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from adp_hypervisor.manifest.index import get_global_manifest_index
from adp_hypervisor.manifest.physical import BackendDefinition, BlobStorageBackendConfig
from adp_hypervisor.protocol.types import (
    IngestIntent,
    Intent,
    LogicOperator,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
    normalize_to_predicate_group,
)
from backends.base import BackendResult
from backends.blob_storage.backend import BlobStorageBackend

logger = logging.getLogger(__name__)

# Convention-based metadata fields for local filesystem entries.
METADATA_FIELD_IDS = frozenset(
    {"path", "size", "last_modified", "created_at", "content_type", "is_directory"}
)


class LocalFSBackend(BlobStorageBackend):
    """Local filesystem backend (BLOB_STORAGE type, ``local`` provider).

    Treats each ADP resource as a directory under the configured root ``uri``.
    Files and subdirectories inside the resource directory are queryable
    entries with convention-based metadata fields.

    Security features:
    - Strict path validation (no traversal)
    - Symlink control via ``allow_symlinks`` config
    - Ignore patterns for path exclusion
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
        if not isinstance(definition.config, BlobStorageBackendConfig):
            raise ValueError(
                f"LocalFSBackend requires BlobStorageBackendConfig, "
                f"got {type(definition.config).__name__!r}"
            )
        self._config: BlobStorageBackendConfig = definition.config
        self._root: Path | None = None
        self._connected: bool = False

    async def connect(self) -> None:
        """Validate root path and establish connection.

        Raises:
            ConnectionError: If the root URI is invalid or inaccessible.
        """
        raw = Path(self._config.uri).expanduser()

        if not self._config.allow_symlinks and raw.is_symlink():
            raise ConnectionError(f"Root path is a symlink (symlinks disabled): {raw}")

        root = raw.resolve()

        if not root.exists():
            raise ConnectionError(f"Root path does not exist: {root}")

        if not root.is_dir():
            raise ConnectionError(f"Root path is not a directory: {root}")

        if not os.access(root, os.R_OK | os.X_OK):
            raise ConnectionError(f"Root path is not readable/traversable: {root}")

        self._root = root
        self._connected = True
        logger.info("Connected to local filesystem backend %s at %s", self.backend_id, root)

    async def disconnect(self) -> None:
        """Close connection and release resources."""
        self._connected = False
        self._root = None
        logger.info("Disconnected local filesystem backend %s", self.backend_id)

    # TODO(#57): offload synchronous filesystem I/O to asyncio.to_thread to
    # avoid blocking the event loop on large directories or files.
    async def execute(self, intent: Intent) -> BackendResult:
        """Execute an intent against the local filesystem.

        Args:
            intent: The intent to execute.

        Returns:
            The execution result containing rows and optional metadata.

        Raises:
            RuntimeError: If backend is not connected or operation fails.
            ValueError: If intent type is unsupported or resource not found.
        """
        if not self._connected or self._root is None:
            raise RuntimeError(f"Backend {self.backend_id!r} is not connected")

        manifest_index = get_global_manifest_index()
        resource = manifest_index.get_resource(intent.resource_id)
        if resource is None:
            raise ValueError(f"Resource not found: {intent.resource_id!r}")

        source = resource.source_definition.source
        if not source:
            raise ValueError(f"Resource {resource.resource_id!r} has empty source")

        source_dir = self._resolve_source_dir(source)

        if isinstance(intent, LookupIntent):
            return self._execute_lookup(source_dir, intent)
        elif isinstance(intent, QueryIntent):
            return self._execute_query(source_dir, intent)
        elif isinstance(intent, IngestIntent):
            return self._execute_ingest(source_dir, intent)
        elif isinstance(intent, ReviseIntent):
            return self._execute_revise(source_dir, intent)
        else:
            raise ValueError(f"Unsupported intent type: {type(intent).__name__}")

    # -------------------------------------------------------------------------
    # Intent execution methods
    # -------------------------------------------------------------------------

    def _execute_lookup(self, source_dir: Path, intent: LookupIntent) -> BackendResult:
        """Execute LOOKUP intent — read a specific file by path.

        Args:
            source_dir: The resolved source directory.
            intent: The LOOKUP intent with key identifying the file.

        Returns:
            Result containing file content and metadata.

        Raises:
            RuntimeError: If file not found or path is invalid.
        """
        if intent.key.field_id != "path":
            raise RuntimeError(f"LOOKUP key field_id must be 'path', got {intent.key.field_id!r}")

        file_path = str(intent.key.value)
        target = self._resolve_child(source_dir, file_path)

        if not target.exists():
            raise RuntimeError(f"File not found: {file_path!r}")

        if not target.is_file():
            raise RuntimeError(f"Path is not a file: {file_path!r}")

        row = self._build_entry_metadata(target, source_dir)

        # TODO(#58): add configurable max file size limit for content retrieval
        # to prevent OOM on very large files.
        content_type = row.get("content_type", "")
        data = target.read_bytes()

        if _is_binary_content_type(content_type) or b"\x00" in data:
            row["content"] = base64.b64encode(data).decode("ascii")
            row["content_encoding"] = "base64"
        else:
            try:
                row["content"] = data.decode("utf-8")
                row["content_encoding"] = "utf-8"
            except UnicodeDecodeError:
                row["content"] = base64.b64encode(data).decode("ascii")
                row["content_encoding"] = "base64"

        if intent.projections:
            row = {k: v for k, v in row.items() if k in intent.projections}

        return BackendResult(rows=[row])

    def _execute_query(self, source_dir: Path, intent: QueryIntent) -> BackendResult:
        """Execute QUERY intent — list entries in a directory.

        Supports directory selection via a ``path EQ <dir>`` predicate.
        When a ``path LIKE`` or ``path ILIKE`` predicate is present, entries are
        collected recursively so that patterns crossing directory boundaries
        (e.g. ``docs/%.txt``) can match.
        At most one ``path`` predicate is allowed per query.

        Args:
            source_dir: The resolved source directory.
            intent: The QUERY intent with optional predicates, limit, order_by.

        Returns:
            Result containing metadata rows (no file content).
        """
        listing_dir = source_dir

        pred_group = normalize_to_predicate_group(intent.predicates)
        path_value, filter_predicates = self._pop_path_eq_predicate(pred_group)

        if path_value is not None:
            target = self._resolve_child(source_dir, path_value)
            if target.is_dir():
                listing_dir = target
            elif target.is_file():
                entry = self._build_entry_metadata(target, source_dir)
                if self._matches_predicates(entry, filter_predicates):
                    file_rows: list[dict[str, Any]] = [entry]
                else:
                    file_rows = []
                if intent.projections:
                    file_rows = [
                        {k: v for k, v in row.items() if k in intent.projections}
                        for row in file_rows
                    ]
                return BackendResult(rows=file_rows)
            else:
                raise RuntimeError(f"Path not found: {path_value!r}")

        rows: list[dict[str, Any]] = []
        can_early_stop = intent.limit is not None and not intent.order_by
        projection_set = set(intent.projections) if intent.projections else None
        # Defer projections when order_by may reference non-projected fields.
        apply_projection_early = projection_set is not None and not intent.order_by

        use_recursive = self._has_path_like_predicate(filter_predicates)
        children = (
            self._iter_entries_recursive(listing_dir)
            if use_recursive
            else sorted(listing_dir.iterdir(), key=lambda p: p.name)
        )

        for child in children:
            if not self._config.allow_symlinks and child.is_symlink():
                continue

            if self._should_ignore(child):
                continue

            entry = self._build_entry_metadata(child, source_dir)

            if not self._matches_predicates(entry, filter_predicates):
                continue

            if apply_projection_early:
                entry = {k: v for k, v in entry.items() if k in projection_set}  # type: ignore[operator]

            rows.append(entry)

            if can_early_stop and len(rows) >= intent.limit:  # type: ignore[operator]
                break

        if intent.order_by:
            for sort_order in reversed(intent.order_by):
                field_id = sort_order.field_id
                reverse = sort_order.direction == "DESC"
                rows.sort(key=lambda r: r.get(field_id, ""), reverse=reverse)

        if intent.limit is not None:
            rows = rows[: intent.limit]

        if projection_set is not None and not apply_projection_early:
            rows = [{k: v for k, v in row.items() if k in projection_set} for row in rows]

        return BackendResult(rows=rows)

    def _execute_ingest(self, source_dir: Path, intent: IngestIntent) -> BackendResult:
        """Execute INGEST intent — create a new file or subdirectory.

        Args:
            source_dir: The resolved source directory.
            intent: The INGEST intent with payload containing path and content.

        Returns:
            Result with status metadata.

        Raises:
            RuntimeError: If payload is invalid or target already exists.
        """
        if not intent.payload:
            raise RuntimeError("INGEST requires a non-empty payload")

        affected = 0
        for item in intent.payload:
            if not isinstance(item, dict):
                raise RuntimeError("Each payload item must be a dict")

            path_value = item.get("path")
            if not path_value or not isinstance(path_value, str):
                raise RuntimeError("Each payload item must have a 'path' field (string)")

            target = self._resolve_child(source_dir, path_value)

            raw_is_dir = item.get("is_directory", False)
            if not isinstance(raw_is_dir, bool):
                raise RuntimeError(
                    f"'is_directory' must be a boolean, got {type(raw_is_dir).__name__!r}"
                )
            is_directory = raw_is_dir
            if is_directory:
                try:
                    target.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    raise RuntimeError(f"Target already exists: {path_value!r}") from None
            else:
                content_bytes = self._decode_content(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with target.open("xb") as f:
                        f.write(content_bytes)
                except FileExistsError:
                    raise RuntimeError(f"Target already exists: {path_value!r}") from None

            affected += 1

        return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": affected})

    def _execute_revise(self, source_dir: Path, intent: ReviseIntent) -> BackendResult:
        """Execute REVISE intent — overwrite an existing file's content.

        Args:
            source_dir: The resolved source directory.
            intent: The REVISE intent with predicates identifying the file
                and payload containing the new content.

        Returns:
            Result with status metadata.

        Raises:
            RuntimeError: If file not found or payload is invalid.
        """
        file_path = self._extract_path_from_predicates(
            normalize_to_predicate_group(intent.predicates)
        )
        if file_path is None:
            raise RuntimeError(
                "REVISE requires a predicate with field_id='path' to identify the file"
            )

        target = self._resolve_child(source_dir, file_path)

        if not target.exists():
            raise RuntimeError(f"File not found: {file_path!r}")

        if not target.is_file():
            raise RuntimeError(f"Path is not a file: {file_path!r}")

        content_bytes = self._decode_content(intent.payload)
        target.write_bytes(content_bytes)

        return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

    # -------------------------------------------------------------------------
    # Path resolution and validation
    # -------------------------------------------------------------------------

    def _resolve_source_dir(self, source: str) -> Path:
        """Resolve and validate the source directory.

        Args:
            source: Relative path from the backend root to the resource directory.

        Returns:
            The resolved absolute directory path.

        Raises:
            ValueError: If source path is invalid.
            RuntimeError: If path escapes root or auto-creation is disabled
                for a missing directory.
        """
        assert self._root is not None

        source_path = Path(source)
        if source_path.is_absolute():
            raise ValueError(f"Source path must be relative: {source!r}")
        if ".." in source_path.parts:
            raise ValueError(f"Path traversal (..) is not allowed: {source!r}")

        target = (self._root / source_path).resolve(strict=False)

        if not self._is_within_root(target):
            raise RuntimeError(f"Source path escapes root: {source!r}")

        if not target.exists():
            if self._config.auto_create_source:
                target.mkdir(parents=True, exist_ok=True)
                logger.info("Auto-created source directory: %s", target)
            else:
                raise RuntimeError(f"Source directory does not exist: {source!r}")
        elif not target.is_dir():
            raise RuntimeError(f"Source path is not a directory: {source!r}")

        return target

    def _resolve_child(self, parent: Path, relative_path: str) -> Path:
        """Resolve and validate a relative path within a directory.

        Supports multi-component paths (e.g., ``"2024/reports/file.csv"``).

        Security checks performed:
        - Path must not be empty, absolute, or contain ``..``
        - Resolved path must stay within ``parent`` (resource boundary)
        - All intermediate path components are checked for symlinks
          when ``allow_symlinks`` is disabled
        - Path must not match any ``ignore_patterns``

        Args:
            parent: The parent directory (resource source root).
            relative_path: Relative path to the target entry.

        Returns:
            The resolved absolute path.

        Raises:
            RuntimeError: If path is empty, absolute, contains ``..``,
                escapes the parent directory, is a symlink when disallowed,
                or matches an ignore pattern.
        """
        if not relative_path or not relative_path.strip():
            raise RuntimeError("Path must not be empty")

        child_path = Path(relative_path)
        if child_path.is_absolute():
            raise RuntimeError(f"Absolute paths are not allowed: {relative_path!r}")
        if ".." in child_path.parts:
            raise RuntimeError(f"Path traversal (..) is not allowed: {relative_path!r}")

        if not self._config.allow_symlinks:
            current = parent
            for part in child_path.parts:
                current = current / part
                if current.is_symlink():
                    raise RuntimeError(f"Symlinks are not allowed: {relative_path!r}")

        target = (parent / child_path).resolve(strict=False)

        try:
            target.relative_to(parent)
        except ValueError:
            raise RuntimeError(f"Path escapes source directory: {relative_path!r}") from None

        if self._should_ignore(target):
            raise RuntimeError(f"Path matches ignore pattern: {relative_path!r}")

        return target

    def _is_within_root(self, target: Path) -> bool:
        """Check if target is within the backend root directory."""
        assert self._root is not None
        try:
            target.relative_to(self._root)
            return True
        except ValueError:
            return False

    # -------------------------------------------------------------------------
    # Metadata and filtering helpers
    # -------------------------------------------------------------------------

    def _build_entry_metadata(self, entry: Path, source_root: Path) -> dict[str, Any]:
        """Build convention-based metadata for a filesystem entry.

        Args:
            entry: Absolute path to the file or directory.
            source_root: The resource's source directory (used to compute
                the relative ``path`` value).

        Returns:
            Dict with metadata fields: path, size, last_modified,
            created_at, content_type, is_directory.
        """
        stat = entry.stat()

        created_ts = getattr(stat, "st_birthtime", None)
        if created_ts is None:
            created_ts = stat.st_ctime

        is_dir = entry.is_dir()
        content_type = "" if is_dir else (mimetypes.guess_type(entry.name)[0] or "")
        rel_path = str(entry.relative_to(source_root)).replace("\\", "/")

        return {
            "path": rel_path,
            "size": 0 if is_dir else stat.st_size,
            "last_modified": _timestamp_to_iso(stat.st_mtime),
            "created_at": _timestamp_to_iso(created_ts),
            "content_type": content_type,
            "is_directory": is_dir,
        }

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored based on ignore patterns.

        Args:
            path: The absolute path to check.

        Returns:
            True if path matches any ignore pattern.
        """
        if not self._config.ignore_patterns:
            return False

        assert self._root is not None
        try:
            rel_path_str = str(path.relative_to(self._root)).replace("\\", "/")
        except ValueError:
            return False

        for pattern in self._config.ignore_patterns:
            if fnmatch.fnmatch(rel_path_str, pattern):
                return True
            for part in Path(rel_path_str).parts:
                if fnmatch.fnmatch(part, pattern):
                    return True

        return False

    def _matches_predicates(self, entry: dict[str, Any], predicates: PredicateGroup | None) -> bool:
        """Check if an entry matches the given predicate group.

        Recursively evaluates nested ``PredicateGroup`` objects, honoring the
        ``op`` field (AND/OR) for combining results.

        Args:
            entry: Metadata dict for a filesystem entry.
            predicates: PredicateGroup from the intent, or None.

        Returns:
            True if the predicate group matches (or no predicates given).
        """
        if predicates is None:
            return True

        if not predicates.predicates:
            return True

        results: list[bool] = []
        for pred in predicates.predicates:
            if isinstance(pred, PredicateGroup):
                results.append(self._matches_predicates(entry, pred))
            elif isinstance(pred, Predicate):
                results.append(self._evaluate_predicate(entry, pred))

        if predicates.op == LogicOperator.OR:
            return any(results)
        elif predicates.op == LogicOperator.AND:
            return all(results)
        else:
            raise RuntimeError(f"Unsupported logic operator: {predicates.op!r}")

    @staticmethod
    def _evaluate_predicate(entry: dict[str, Any], pred: Predicate) -> bool:
        """Evaluate a single predicate against an entry.

        Args:
            entry: Metadata dict for a filesystem entry.
            pred: The predicate to evaluate.

        Returns:
            True if the predicate matches.

        Raises:
            RuntimeError: If the operator is unsupported by this backend.
        """
        field_id = pred.field_id
        if field_id not in entry:
            return True

        entry_val = entry[field_id]
        pred_val = pred.value

        if pred.op == PredicateOperator.EQ:
            return entry_val == pred_val  # type: ignore[no-any-return]
        elif pred.op == PredicateOperator.NEQ:
            return entry_val != pred_val  # type: ignore[no-any-return]
        elif pred.op in (
            PredicateOperator.GT,
            PredicateOperator.GTE,
            PredicateOperator.LT,
            PredicateOperator.LTE,
        ):
            both_numeric = isinstance(entry_val, (int, float)) and isinstance(
                pred_val, (int, float)
            )
            if not both_numeric and type(entry_val) is not type(pred_val):
                raise RuntimeError(
                    f"Type mismatch: field {field_id!r} is {type(entry_val).__name__}, "
                    f"but predicate value is {type(pred_val).__name__}"
                )
            if pred.op == PredicateOperator.GT:
                return entry_val > pred_val  # type: ignore[no-any-return]
            elif pred.op == PredicateOperator.GTE:
                return entry_val >= pred_val  # type: ignore[no-any-return]
            elif pred.op == PredicateOperator.LT:
                return entry_val < pred_val  # type: ignore[no-any-return]
            else:
                return entry_val <= pred_val  # type: ignore[no-any-return]
        elif pred.op == PredicateOperator.LIKE:
            if isinstance(pred_val, str) and isinstance(entry_val, str):
                pattern = pred_val.replace("%", "*").replace("_", "?")
                return fnmatch.fnmatch(entry_val, pattern)
            return False
        elif pred.op == PredicateOperator.ILIKE:
            if isinstance(pred_val, str) and isinstance(entry_val, str):
                pattern = pred_val.replace("%", "*").replace("_", "?")
                return fnmatch.fnmatch(entry_val.lower(), pattern.lower())
            return False
        elif pred.op == PredicateOperator.CONTAINS:
            if isinstance(pred_val, str) and isinstance(entry_val, str):
                return pred_val in entry_val
            return False
        elif pred.op == PredicateOperator.IN:
            if isinstance(pred_val, list):
                return entry_val in pred_val
            return False
        else:
            raise RuntimeError(
                f"Unsupported predicate operator for local filesystem backend: {pred.op!r}"
            )

    @staticmethod
    def _has_path_like_predicate(predicates: PredicateGroup | None) -> bool:
        """Check recursively whether any predicate targets ``path`` with LIKE or ILIKE.

        Args:
            predicates: The predicate group to inspect.

        Returns:
            True if a ``path LIKE`` or ``path ILIKE`` predicate exists anywhere
            in the group tree.
        """
        if predicates is None:
            return False
        for pred in predicates.predicates:
            if isinstance(pred, Predicate):
                if pred.field_id == "path" and pred.op in (
                    PredicateOperator.LIKE,
                    PredicateOperator.ILIKE,
                ):
                    return True
            elif isinstance(pred, PredicateGroup):
                if LocalFSBackend._has_path_like_predicate(pred):
                    return True
        return False

    def _iter_entries_recursive(self, root: Path) -> Iterator[Path]:
        """Yield all filesystem entries under *root* in deterministic traversal order.

        Uses ``os.walk`` with ``topdown=True`` so that ignored directories are
        pruned before being descended into, avoiding unnecessary I/O. Symbolic
        links to directories are never followed; they appear as leaf entries
        only, preventing directory escape and infinite cycles.

        Each directory level yields files and subdirectories sorted by name,
        matching the ordering used by the non-recursive listing path.

        Args:
            root: Directory to walk.

        Yields:
            Path objects for each filesystem entry (files and directories)
            under root, in per-directory alphabetical order.
        """
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            dir_path = Path(dirpath)
            # Prune ignored directories in-place so os.walk does not descend
            # into them, and sort for deterministic traversal order.
            dirnames[:] = sorted(d for d in dirnames if not self._should_ignore(dir_path / d))
            # Yield files and directories at this level mixed by name, matching
            # the sort order of sorted(iterdir(), key=lambda p: p.name).
            for name in sorted(filenames + dirnames):
                yield dir_path / name

    def _pop_path_eq_predicate(
        self, predicates: PredicateGroup | None
    ) -> tuple[str | None, PredicateGroup | None]:
        """Extract a ``path EQ`` predicate for directory/file selection in QUERY.

        Validates that at most one ``path`` predicate exists at the top level.
        If the predicate uses EQ, it is consumed (removed from the returned
        group) and its value is returned for directory/file resolution.
        Non-EQ ``path`` predicates are kept as regular filters.

        Args:
            predicates: The top-level predicate group.

        Returns:
            A tuple of (path_value, remaining_predicates).

        Raises:
            RuntimeError: If more than one ``path`` predicate exists at the
                top level.
        """
        if predicates is None:
            return None, None

        path_preds = [
            p for p in predicates.predicates if isinstance(p, Predicate) and p.field_id == "path"
        ]

        if len(path_preds) > 1:
            raise RuntimeError("Only one 'path' predicate is allowed per query")

        if not path_preds:
            return None, predicates

        path_pred = path_preds[0]
        if path_pred.op != PredicateOperator.EQ:
            return None, predicates

        remaining = [p for p in predicates.predicates if p is not path_pred]
        remaining_group = PredicateGroup(predicates=remaining, op=predicates.op)
        return str(path_pred.value), remaining_group

    @staticmethod
    def _extract_path_from_predicates(predicates: PredicateGroup | None) -> str | None:
        """Extract the ``path`` value from a predicate group.

        Recursively searches nested groups for a ``path EQ <value>`` predicate.
        Unlike ``_pop_path_eq_predicate`` (used by QUERY), this method does not
        remove the predicate from the group — it only extracts the value.

        Args:
            predicates: PredicateGroup from the intent.

        Returns:
            The path string, or None if not found.

        Raises:
            RuntimeError: If more than one ``path`` predicate exists.
        """
        if predicates is None:
            return None

        def _collect_path_predicates(group: PredicateGroup) -> list[Predicate]:
            found: list[Predicate] = []
            for pred in group.predicates:
                if isinstance(pred, Predicate) and pred.field_id == "path":
                    found.append(pred)
                elif isinstance(pred, PredicateGroup):
                    found.extend(_collect_path_predicates(pred))
            return found

        path_preds = _collect_path_predicates(predicates)

        if len(path_preds) > 1:
            raise RuntimeError("Only one 'path' predicate is allowed")

        if not path_preds:
            return None

        path_pred = path_preds[0]
        if path_pred.op != PredicateOperator.EQ:
            return None

        return str(path_pred.value)

    @staticmethod
    def _decode_content(item: dict[str, Any]) -> bytes:
        """Decode content from a payload item.

        Args:
            item: Dict containing ``content`` and optional ``content_encoding``.

        Returns:
            Raw bytes of the content.

        Raises:
            RuntimeError: If content is missing or encoding is unsupported.
        """
        content = item.get("content")
        if content is None:
            raise RuntimeError("Payload item must have a 'content' field")

        encoding = str(item.get("content_encoding", "utf-8")).lower()

        if encoding == "base64":
            if not isinstance(content, str):
                raise RuntimeError("base64 content must be a string")
            try:
                return base64.b64decode(content, validate=True)
            except Exception as e:
                raise RuntimeError(f"Invalid base64 content: {e}") from None
        elif encoding == "utf-8":
            if isinstance(content, str):
                return content.encode("utf-8")
            elif isinstance(content, bytes):
                return content
            else:
                raise RuntimeError("utf-8 content must be a string or bytes")
        else:
            raise RuntimeError(f"Unsupported content_encoding: {encoding!r}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _timestamp_to_iso(ts: float) -> str:
    """Convert a Unix timestamp to an ISO 8601 string (UTC, Z suffix)."""
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _is_binary_content_type(content_type: str) -> bool:
    """Heuristic: return True if the MIME type indicates binary data.

    Treats ``text/*`` as text and all other non-empty MIME types as binary.
    Unknown (empty) content types are treated as potentially text so that
    the byte-level fallback logic can decide.
    """
    if not content_type:
        return False
    return not content_type.startswith("text/")
