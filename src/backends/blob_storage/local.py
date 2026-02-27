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
)
from backends.base import BackendResult
from backends.blob_storage.backend import BlobStorageBackend

logger = logging.getLogger(__name__)

# Convention-based metadata fields for local filesystem entries.
METADATA_FIELD_IDS = frozenset(
    {"name", "size", "last_modified", "created_at", "content_type", "is_directory"}
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
        root = Path(self._config.uri).expanduser().resolve()

        if not root.exists():
            raise ConnectionError(f"Root path does not exist: {root}")

        if not root.is_dir():
            raise ConnectionError(f"Root path is not a directory: {root}")

        if not os.access(root, os.R_OK | os.X_OK):
            raise ConnectionError(f"Root path is not readable/traversable: {root}")

        if not self._config.allow_symlinks and root.is_symlink():
            raise ConnectionError(f"Root path is a symlink (symlinks disabled): {root}")

        self._root = root
        self._connected = True
        logger.info("Connected to local filesystem backend %s at %s", self.backend_id, root)

    async def disconnect(self) -> None:
        """Close connection and release resources."""
        self._connected = False
        self._root = None
        logger.info("Disconnected local filesystem backend %s", self.backend_id)

    # TODO: offload synchronous filesystem I/O to asyncio.to_thread to avoid
    # blocking the event loop on large directories or files.
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
        """Execute LOOKUP intent — read a specific file by name.

        Args:
            source_dir: The resolved source directory.
            intent: The LOOKUP intent with key identifying the file.

        Returns:
            Result containing file content and metadata.

        Raises:
            RuntimeError: If file not found or path is invalid.
        """
        if intent.key.field_id != "name":
            raise RuntimeError(f"LOOKUP key field_id must be 'name', got {intent.key.field_id!r}")

        file_name = str(intent.key.value)
        target = self._resolve_child(source_dir, file_name)

        if not target.exists():
            raise RuntimeError(f"File not found: {file_name!r}")

        if not target.is_file():
            raise RuntimeError(f"Path is not a file: {file_name!r}")

        row = self._build_entry_metadata(target)

        # TODO: add configurable max file size limit for content retrieval to
        # prevent OOM on very large files.
        content_type = row.get("content_type", "")
        if _is_binary_content_type(content_type):
            data = target.read_bytes()
            row["content"] = base64.b64encode(data).decode("ascii")
            row["content_encoding"] = "base64"
        else:
            row["content"] = target.read_text(encoding="utf-8", errors="replace")
            row["content_encoding"] = "utf-8"

        if intent.projections:
            row = {k: v for k, v in row.items() if k in intent.projections}

        return BackendResult(rows=[row])

    def _execute_query(self, source_dir: Path, intent: QueryIntent) -> BackendResult:
        """Execute QUERY intent — list files in the directory.

        Args:
            source_dir: The resolved source directory.
            intent: The QUERY intent with optional predicates, limit, order_by.

        Returns:
            Result containing metadata rows (no file content).
        """
        rows: list[dict[str, Any]] = []

        # TODO: for very large directories, consider lazy iteration with
        # os.scandir and early limit cutoff to reduce memory usage.
        for child in sorted(source_dir.iterdir(), key=lambda p: p.name):
            if not self._config.allow_symlinks and child.is_symlink():
                continue

            if self._should_ignore(child):
                continue

            entry = self._build_entry_metadata(child)

            if not self._matches_predicates(entry, intent.predicates):
                continue

            rows.append(entry)

        if intent.order_by:
            for sort_order in reversed(intent.order_by):
                field_id = sort_order.field_id
                reverse = sort_order.direction == "DESC"
                rows.sort(key=lambda r: r.get(field_id, ""), reverse=reverse)

        if intent.limit is not None:
            rows = rows[: intent.limit]

        if intent.projections:
            rows = [{k: v for k, v in row.items() if k in intent.projections} for row in rows]

        return BackendResult(rows=rows)

    def _execute_ingest(self, source_dir: Path, intent: IngestIntent) -> BackendResult:
        """Execute INGEST intent — create a new file or subdirectory.

        Args:
            source_dir: The resolved source directory.
            intent: The INGEST intent with payload containing name and content.

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

            name = item.get("name")
            if not name or not isinstance(name, str):
                raise RuntimeError("Each payload item must have a 'name' field (string)")

            target = self._resolve_child(source_dir, name)

            is_directory = bool(item.get("is_directory", False))
            if is_directory:
                try:
                    target.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    raise RuntimeError(f"Target already exists: {name!r}") from None
            else:
                content_bytes = self._decode_content(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with target.open("xb") as f:
                        f.write(content_bytes)
                except FileExistsError:
                    raise RuntimeError(f"Target already exists: {name!r}") from None

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
        file_name = self._extract_name_from_predicates(intent.predicates)
        if file_name is None:
            raise RuntimeError(
                "REVISE requires a predicate with field_id='name' to identify the file"
            )

        target = self._resolve_child(source_dir, file_name)

        if not target.exists():
            raise RuntimeError(f"File not found: {file_name!r}")

        if not target.is_file():
            raise RuntimeError(f"Path is not a file: {file_name!r}")

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

    def _resolve_child(self, parent: Path, name: str) -> Path:
        """Resolve and validate a child path within a directory.

        Args:
            parent: The parent directory.
            name: The child file/directory name.

        Returns:
            The resolved absolute child path.

        Raises:
            RuntimeError: If name contains path separators, traversal, or
                escapes the parent directory.
        """
        if os.sep in name or (os.altsep and os.altsep in name):
            raise RuntimeError(f"Name must not contain path separators: {name!r}")
        if name in (".", ".."):
            raise RuntimeError(f"Invalid name: {name!r}")

        target = (parent / name).resolve(strict=False)

        if not self._is_within_root(target):
            raise RuntimeError(f"Path escapes root: {name!r}")

        if not self._config.allow_symlinks and (parent / name).is_symlink():
            raise RuntimeError(f"Symlinks are not allowed: {name!r}")

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

    def _build_entry_metadata(self, path: Path) -> dict[str, Any]:
        """Build convention-based metadata for a filesystem entry.

        Args:
            path: Absolute path to the file or directory.

        Returns:
            Dict with metadata fields: name, size, last_modified,
            created_at, content_type, is_directory.
        """
        stat = path.stat()

        created_ts = getattr(stat, "st_birthtime", None)
        if created_ts is None:
            created_ts = stat.st_ctime

        is_dir = path.is_dir()
        content_type = "" if is_dir else (mimetypes.guess_type(path.name)[0] or "")

        return {
            "name": path.name,
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
            if type(entry_val) is not type(pred_val):
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
    def _extract_name_from_predicates(predicates: PredicateGroup | None) -> str | None:
        """Extract the ``name`` value from a predicate group.

        Recursively searches nested groups for a ``name == <value>`` predicate.

        Args:
            predicates: PredicateGroup from the intent.

        Returns:
            The name string, or None if not found.
        """
        if predicates is None:
            return None

        for pred in predicates.predicates:
            if isinstance(pred, Predicate) and pred.field_id == "name" and pred.op == "EQ":
                return str(pred.value)
            if isinstance(pred, PredicateGroup):
                result = LocalFSBackend._extract_name_from_predicates(pred)
                if result is not None:
                    return result

        return None

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
    """Heuristic: return True if the MIME type indicates binary data."""
    if not content_type:
        return False
    binary_prefixes = ("image/", "audio/", "video/", "application/octet-stream")
    return content_type.startswith(binary_prefixes)
