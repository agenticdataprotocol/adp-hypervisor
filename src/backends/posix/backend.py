"""
POSIX Filesystem Backend.

Provides ADP Intent-based access to POSIX-compliant filesystems.
Based on the prototype implementation with enhanced security and validation.
"""

import base64
import fnmatch
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adp_hypervisor.manifest.physical import BackendDefinition, POSIXBackendConfig
from adp_hypervisor.protocol.types import (
    IngestIntent,
    Intent,
    IssueSeverity,
    LookupIntent,
    Predicate,
    PredicateGroup,
    QueryIntent,
    ReviseIntent,
    ValidationIssue,
    ValidationIssueCode,
)
from backends.base import Backend, BackendResult

logger = logging.getLogger(__name__)


class POSIXBackend(Backend):
    """POSIX filesystem backend.

    Provides Intent-based access to local or network-mounted POSIX filesystems.
    Treats files and directories as queryable resources with metadata fields.

    Security features:
    - Strict path validation (no traversal, no symlinks by default)
    - Root path allowlist enforcement
    - Canonical path resolution
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
        if not isinstance(definition.config, POSIXBackendConfig):
            raise ValueError(
                f"POSIXBackend requires POSIXBackendConfig, "
                f"got {type(definition.config).__name__}"
            )
        self._config: POSIXBackendConfig = definition.config
        self._root_paths: list[Path] = []
        self._connected: bool = False

    async def connect(self) -> None:
        """Validate root paths and establish connection.

        Raises:
            ConnectionError: If any root path is invalid or inaccessible.
        """
        if not self._config.root_paths:
            raise ConnectionError(
                f"POSIXBackend {self.backend_id!r} requires at least one root path"
            )

        root_paths: list[Path] = []
        for root_str in self._config.root_paths:
            root = Path(root_str).expanduser().resolve()

            # Validate root path
            if not root.exists():
                raise ConnectionError(f"Root path does not exist: {root}")

            if not root.is_dir():
                raise ConnectionError(f"Root path is not a directory: {root}")

            if not os.access(root, os.R_OK):
                raise ConnectionError(f"Root path is not readable: {root}")

            # Check for symlinks if not allowed
            if not self._config.allow_symlinks and root.is_symlink():
                raise ConnectionError(f"Root path is a symlink: {root}")

            root_paths.append(root)
            logger.debug("Validated root path: %s", root)

        self._root_paths = root_paths
        self._connected = True
        logger.info(
            "Connected to POSIX backend %s with %d root path(s)",
            self.backend_id,
            len(self._root_paths),
        )

    async def disconnect(self) -> None:
        """Close connection and release resources."""
        self._connected = False
        self._root_paths = []
        logger.info("Disconnected POSIX backend %s", self.backend_id)

    async def validate(self, source: str, intent: Intent) -> list[ValidationIssue]:
        """Validate an intent against the filesystem.

        Args:
            source: The source identifier (resource path).
            intent: The intent to validate.

        Returns:
            A list of validation issues. An empty list means the intent is valid.
        """
        issues: list[ValidationIssue] = []

        try:
            self._require_connection()
        except RuntimeError as exc:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.INVALID_FORMAT,
                    severity=IssueSeverity.BLOCKING,
                    message=str(exc),
                )
            )
            return issues

        # Validate path resolution
        try:
            root_path, resource_path = self._parse_source(source)
            target = self._resolve_target(root_path, resource_path, allow_missing=True)

            # Check if path is ignored
            if self._should_ignore(target, root_path):
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.FIELD_NOT_FOUND,
                        severity=IssueSeverity.BLOCKING,
                        message=f"Path is ignored by ignore patterns: {source}",
                    )
                )
                return issues

        except (ValueError, RuntimeError) as exc:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.INVALID_FORMAT,
                    severity=IssueSeverity.BLOCKING,
                    message=f"Invalid source path: {exc}",
                )
            )
            return issues

        # Intent-specific validation
        if isinstance(intent, LookupIntent):
            # LOOKUP requires existing resource
            if not target.exists():
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.FIELD_NOT_FOUND,
                        severity=IssueSeverity.BLOCKING,
                        message=f"Resource not found: {source}",
                    )
                )

        elif isinstance(intent, QueryIntent):
            # QUERY requires existing resource
            if not target.exists():
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.FIELD_NOT_FOUND,
                        severity=IssueSeverity.BLOCKING,
                        message=f"Resource not found: {source}",
                    )
                )

        elif isinstance(intent, IngestIntent):
            # INGEST can create new resources
            pass

        elif isinstance(intent, ReviseIntent):
            # REVISE requires existing resource
            if not target.exists():
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.FIELD_NOT_FOUND,
                        severity=IssueSeverity.BLOCKING,
                        message=f"Resource not found: {source}",
                    )
                )

        return issues

    async def execute(self, source: str, intent: Intent) -> BackendResult:
        """Execute an intent against the filesystem.

        Args:
            source: The source identifier (format: "root_path|resource_path" or "resource_path").
            intent: The intent to execute.

        Returns:
            The execution result containing rows and optional metadata.

        Raises:
            RuntimeError: If backend is not connected or operation fails.
            ValueError: If intent type is unsupported.
        """
        self._require_connection()

        if isinstance(intent, LookupIntent):
            return await self._execute_lookup(source, intent)
        elif isinstance(intent, QueryIntent):
            return await self._execute_query(source, intent)
        elif isinstance(intent, IngestIntent):
            return await self._execute_ingest(source, intent)
        elif isinstance(intent, ReviseIntent):
            return await self._execute_revise(source, intent)
        else:
            raise ValueError(f"Unsupported intent type: {type(intent).__name__}")

    # -------------------------------------------------------------------------
    # Intent execution methods
    # -------------------------------------------------------------------------

    async def _execute_lookup(self, source: str, intent: LookupIntent) -> BackendResult:
        """Execute LOOKUP intent (same as IDENTIFY in prototype).

        Returns metadata about a single file or directory.
        """
        root_path, resource_path = self._parse_source(source)
        target = self._resolve_target(root_path, resource_path)

        if not target.exists():
            raise RuntimeError(f"Resource not found: {source}")

        # Check if path is ignored
        if self._should_ignore(target, root_path):
            raise RuntimeError(f"Path is ignored by ignore patterns: {source}")

        object_type = self._get_object_type(target)

        if object_type == "directory":
            row: dict[str, Any] = {
                "name": target.name,
                "path": str(resource_path),
                "mtime": self._iso_time(target.stat().st_mtime),
                "object_type": "directory",
            }
        else:
            st = target.stat()
            row = {
                "name": target.name,
                "path": str(resource_path),
                "extension": target.suffix.lstrip(".") if target.suffix else "",
                "size": st.st_size,
                "mtime": self._iso_time(st.st_mtime),
                "atime": self._iso_time(st.st_atime),
                "object_type": "file",
            }

        # Apply projections if specified
        if intent.projections:
            row = {k: v for k, v in row.items() if k in intent.projections}

        return BackendResult(rows=[row])

    async def _execute_query(self, source: str, intent: QueryIntent) -> BackendResult:
        """Execute QUERY intent.

        For directories: list children
        For files: return content
        """
        root_path, resource_path = self._parse_source(source)
        target = self._resolve_target(root_path, resource_path)

        if not target.exists():
            raise RuntimeError(f"Resource not found: {source}")

        # Check if path is ignored
        if self._should_ignore(target, root_path):
            raise RuntimeError(f"Path is ignored by ignore patterns: {source}")

        object_type = self._get_object_type(target)

        if object_type == "directory":
            # List directory children
            children: list[dict[str, Any]] = []
            for child in sorted(target.iterdir(), key=lambda p: p.name):
                # Skip symlinks if not allowed
                if not self._config.allow_symlinks and child.is_symlink():
                    logger.warning("Skipping symlink: %s", child)
                    continue

                # Skip ignored paths
                if self._should_ignore(child, root_path):
                    logger.debug("Skipping ignored path: %s", child)
                    continue

                child_info = {"name": child.name}

                # Add additional fields if requested
                if intent.projections and "object_type" in intent.projections:
                    child_info["object_type"] = "directory" if child.is_dir() else "file"

                children.append(child_info)

            # Apply limit if specified
            if intent.limit is not None:
                children = children[: intent.limit]

            return BackendResult(rows=children)

        else:
            # Read file content
            content_format = self._extract_content_format(intent.predicates)

            if content_format == "uri":
                content = f"file://{target.resolve()}"
            else:
                data = target.read_bytes()
                if content_format == "base64":
                    content = base64.b64encode(data).decode("ascii")
                else:  # raw
                    content = data.decode("utf-8", errors="replace")

            row = {
                "name": target.name,
                "path": str(resource_path),
                "content": content,
                "content_format": content_format,
            }

            # Apply projections if specified
            if intent.projections:
                row = {k: v for k, v in row.items() if k in intent.projections}

            return BackendResult(rows=[row])

    async def _execute_ingest(self, source: str, intent: IngestIntent) -> BackendResult:
        """Execute INGEST intent.

        Creates new files or directories.
        """
        root_path, resource_path = self._parse_source(source)
        target = self._resolve_target(root_path, resource_path, allow_missing=True)

        # Check if path is ignored
        if self._should_ignore(target, root_path):
            raise RuntimeError(f"Cannot create ignored path: {source}")

        # Check if target exists - for INGEST, we typically don't allow overwrite
        # unless specified in the payload
        if target.exists():
            # Check payload for overwrite flag
            overwrite = False
            if intent.payload and len(intent.payload) > 0:
                first_item = intent.payload[0]
                if isinstance(first_item, dict):
                    overwrite = bool(first_item.get("overwrite_existing", False))

            if not overwrite:
                raise RuntimeError(
                    f"Target already exists: {source}. Set overwrite_existing=true to overwrite."
                )

        # Determine object type from payload
        object_type = "file"  # default
        if intent.payload and len(intent.payload) > 0:
            first_item = intent.payload[0]
            if isinstance(first_item, dict):
                object_type = first_item.get("object_type", "file").lower()

        if object_type == "directory":
            if target.exists():
                return BackendResult(rows=[], metadata={"status": "NOOP", "affected": 0})
            target.mkdir(parents=True, exist_ok=True)
            return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

        else:
            # Create file with content
            content, content_format = self._extract_content(intent)
            self._write_content(target, content, mode="overwrite")
            return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

    async def _execute_revise(self, source: str, intent: ReviseIntent) -> BackendResult:
        """Execute REVISE intent.

        Supports: rename, move, update_metadata, overwrite, append, delete.
        """
        root_path, resource_path = self._parse_source(source)
        target = self._resolve_target(root_path, resource_path)

        if not target.exists():
            raise RuntimeError(f"Resource not found: {source}")

        # Check if path is ignored
        if self._should_ignore(target, root_path):
            raise RuntimeError(f"Cannot modify ignored path: {source}")

        object_type = self._get_object_type(target)

        # Check for function-based operations
        function_name, function_args = self._extract_function(intent)

        if function_name:
            if function_name in {"rename", "move"}:
                new_path_str = function_args.get("new_path") or function_args.get("new_name")
                if not new_path_str:
                    raise RuntimeError("Missing new_path or new_name for rename/move")

                # Handle relative new_name
                if "new_name" in function_args and "new_path" not in function_args:
                    new_path_str = str(resource_path.parent / new_path_str)

                dest = self._resolve_target(root_path, Path(new_path_str), allow_missing=True)

                # Check if destination is ignored
                if self._should_ignore(dest, root_path):
                    raise RuntimeError(f"Cannot move to ignored path: {new_path_str}")

                target.rename(dest)
                return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

            elif function_name == "update_metadata":
                mtime = function_args.get("mtime")
                atime = function_args.get("atime")

                current_stat = target.stat()
                atime_ts = self._parse_time(atime) if atime is not None else current_stat.st_atime
                mtime_ts = self._parse_time(mtime) if mtime is not None else current_stat.st_mtime

                os.utime(target, (atime_ts, mtime_ts))
                return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

            elif function_name in {"overwrite", "append"}:
                if object_type == "directory":
                    raise RuntimeError("Cannot update directory content")

                content, content_format = self._extract_content(intent)
                mode = "append" if function_name == "append" else "overwrite"
                self._write_content(target, content, mode=mode)
                return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

            elif function_name == "delete":
                # Handle delete via REVISE (alternative to PRUNE intent)
                recursive = function_args.get("recursive", False)

                if object_type == "directory":
                    entries = list(target.iterdir())
                    if entries and not recursive:
                        raise RuntimeError("Directory is not empty. Set recursive=true to delete.")
                    if recursive:
                        shutil.rmtree(target)
                    else:
                        target.rmdir()
                else:
                    target.unlink()

                return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

            else:
                raise RuntimeError(f"Unsupported function: {function_name!r}")

        # Default: content update (overwrite)
        if object_type == "directory":
            raise RuntimeError("Cannot update directory content without function")

        content, content_format = self._extract_content(intent)
        self._write_content(target, content, mode="overwrite")
        return BackendResult(rows=[], metadata={"status": "SUCCESS", "affected": 1})

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _require_connection(self) -> None:
        """Ensure backend is connected.

        Raises:
            RuntimeError: If not connected.
        """
        if not self._connected:
            raise RuntimeError(f"Backend {self.backend_id!r} is not connected")

    def _should_ignore(self, path: Path, root: Path) -> bool:
        """Check if path should be ignored based on ignore patterns.

        Args:
            path: The path to check (absolute).
            root: The root path to calculate relative path from.

        Returns:
            True if path matches any ignore pattern, False otherwise.
        """
        if not self._config.ignore_patterns:
            return False

        # Get path relative to root for pattern matching
        try:
            rel_path = path.relative_to(root)
        except ValueError:
            # Path is not relative to root, don't ignore
            return False

        # Convert to string with forward slashes (gitignore style)
        rel_path_str = str(rel_path).replace("\\", "/")

        # Check against each pattern
        for pattern in self._config.ignore_patterns:
            # Support both file and directory patterns
            if fnmatch.fnmatch(rel_path_str, pattern):
                logger.debug("Ignoring path %s (matches pattern %s)", rel_path_str, pattern)
                return True

            # Also check if any parent directory matches (for directory patterns)
            parts = rel_path_str.split("/")
            for i in range(1, len(parts) + 1):
                partial = "/".join(parts[:i])
                if fnmatch.fnmatch(partial, pattern):
                    logger.debug(
                        "Ignoring path %s (parent %s matches pattern %s)",
                        rel_path_str,
                        partial,
                        pattern,
                    )
                    return True

        return False

    def _parse_source(self, source: str) -> tuple[Path, Path]:
        """Parse source string into root_path and resource_path.

        Format: "root_path|resource_path" or just "resource_path" (uses first root).

        Args:
            source: The source identifier.

        Returns:
            Tuple of (root_path, resource_path).

        Raises:
            ValueError: If source format is invalid.
        """
        if "|" in source:
            root_str, resource_str = source.split("|", 1)
            root_path = Path(root_str).expanduser().resolve()

            # Validate root is in allowed list
            if root_path not in self._root_paths:
                raise ValueError(f"Root path not allowed: {root_path}")
        else:
            # Use first root path
            if not self._root_paths:
                raise ValueError("No root paths configured")
            root_path = self._root_paths[0]
            resource_str = source

        resource_path = Path(resource_str)

        # Validate resource path
        if resource_path.is_absolute():
            raise ValueError("Resource path must be relative")

        if ".." in resource_path.parts:
            raise ValueError("Path traversal (..) is not allowed")

        return root_path, resource_path

    def _resolve_target(self, root: Path, resource_path: Path, allow_missing: bool = False) -> Path:
        """Resolve and validate target path.

        Args:
            root: The root directory path.
            resource_path: The relative resource path.
            allow_missing: Whether to allow non-existent paths.

        Returns:
            The resolved absolute path.

        Raises:
            RuntimeError: If path is invalid or escapes root.
        """
        target = (root / resource_path).resolve(strict=False)

        # Ensure target is within root
        if not self._is_within_root(root, target):
            raise RuntimeError(f"Resolved path escapes root: {target}")

        # Check for symlinks in path
        if not self._config.allow_symlinks:
            self._assert_no_symlink(root, target, allow_missing=allow_missing)

        return target

    def _is_within_root(self, root: Path, target: Path) -> bool:
        """Check if target is within root directory.

        Args:
            root: The root directory.
            target: The target path to check.

        Returns:
            True if target is within root, False otherwise.
        """
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    def _assert_no_symlink(self, root: Path, target: Path, allow_missing: bool) -> None:
        """Assert that no component in the path is a symlink.

        Args:
            root: The root directory.
            target: The target path to check.
            allow_missing: Whether to allow non-existent paths.

        Raises:
            RuntimeError: If any path component is a symlink.
        """
        current = root
        if current.is_symlink():
            raise RuntimeError(f"Symlinks are not allowed: {current}")

        parts = target.relative_to(root).parts
        for part in parts:
            current = current / part
            if current.exists():
                if current.is_symlink():
                    raise RuntimeError(f"Symlinks are not allowed: {current}")
            elif not allow_missing:
                break

    def _get_object_type(self, target: Path) -> str:
        """Determine object type (file or directory).

        Args:
            target: The target path.

        Returns:
            "directory" or "file".
        """
        return "directory" if target.is_dir() else "file"

    def _extract_content_format(self, predicates: PredicateGroup) -> str:
        """Extract content_format from predicates.

        Args:
            predicates: The predicate group.

        Returns:
            Content format: "raw", "base64", or "uri".
        """
        for pred in predicates.predicates:
            if isinstance(pred, Predicate) and pred.field_id == "content_format":
                if isinstance(pred.value, str):
                    fmt = pred.value.lower()
                    if fmt in {"raw", "base64", "uri"}:
                        return fmt
        return "raw"

    def _extract_flag(self, predicates: PredicateGroup, flag_name: str) -> bool:
        """Extract boolean flag from predicates.

        Args:
            predicates: The predicate group.
            flag_name: The flag field name.

        Returns:
            The flag value, or False if not found.
        """
        for pred in predicates.predicates:
            if isinstance(pred, Predicate) and pred.field_id == flag_name:
                return bool(pred.value)
        return False

    def _extract_content(self, intent: IngestIntent | ReviseIntent) -> tuple[bytes, str]:
        """Extract content and format from intent.

        Args:
            intent: The INGEST or REVISE intent.

        Returns:
            Tuple of (content_bytes, content_format).

        Raises:
            RuntimeError: If content is missing or invalid.
        """
        # For IngestIntent, content is in the payload list
        if isinstance(intent, IngestIntent):
            if not intent.payload or len(intent.payload) == 0:
                raise RuntimeError("Missing payload for INGEST")

            # Use first item in payload
            value = intent.payload[0]
            if isinstance(value, dict):
                content_str = value.get("content", "")
                content_format = value.get("content_format", "raw")
            else:
                content_str = str(value)
                content_format = "raw"

        # For ReviseIntent, check payload
        elif isinstance(intent, ReviseIntent):
            if not isinstance(intent.payload, dict):
                raise RuntimeError("Missing payload for REVISE")

            content_str = intent.payload.get("content", "")
            content_format = intent.payload.get("content_format", "raw")

        else:
            raise RuntimeError(f"Unsupported intent type: {type(intent).__name__}")

        # Decode content based on format
        content_format = content_format.lower() if isinstance(content_format, str) else "raw"

        if content_format == "base64":
            if not isinstance(content_str, str):
                raise RuntimeError("Content must be base64 string")
            return base64.b64decode(content_str), content_format

        elif content_format == "raw":
            if isinstance(content_str, str):
                return content_str.encode("utf-8"), content_format
            elif isinstance(content_str, bytes):
                return content_str, content_format
            else:
                raise RuntimeError("Content must be string or bytes")

        else:
            raise RuntimeError(f"Unsupported content_format: {content_format}")

    def _extract_function(self, intent: ReviseIntent) -> tuple[str | None, dict[str, Any]]:
        """Extract function name and args from REVISE intent.

        Args:
            intent: The REVISE intent.

        Returns:
            Tuple of (function_name, function_args).
        """
        if not isinstance(intent.payload, dict):
            return None, {}

        function = intent.payload.get("function")
        if not isinstance(function, dict):
            return None, {}

        name = function.get("name")
        args = function.get("args", {})

        if not isinstance(name, str):
            return None, {}

        if not isinstance(args, dict):
            args = {}

        return name, args

    def _write_content(self, target: Path, content: bytes, mode: str) -> None:
        """Write content to file.

        Args:
            target: The target file path.
            content: The content bytes to write.
            mode: Write mode ("overwrite" or "append").
        """
        target.parent.mkdir(parents=True, exist_ok=True)

        write_mode = "ab" if mode == "append" else "wb"
        with target.open(write_mode) as f:
            f.write(content)

    def _parse_time(self, value: Any) -> float:
        """Parse time value to Unix timestamp.

        Args:
            value: Time value (int, float, or ISO string).

        Returns:
            Unix timestamp as float.

        Raises:
            RuntimeError: If time format is invalid.
        """
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.timestamp()
            except ValueError as exc:
                raise RuntimeError(f"Invalid time format: {value}") from exc

        raise RuntimeError(f"Invalid time type: {type(value).__name__}")

    def _iso_time(self, ts: float) -> str:
        """Convert Unix timestamp to ISO 8601 string.

        Args:
            ts: Unix timestamp.

        Returns:
            ISO 8601 formatted string with Z suffix.
        """
        return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")
