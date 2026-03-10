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
High-level manifest query helper built on top of ManifestProvider.

This class is responsible for building in-memory indexes over the raw
Physical/Semantic/Policy manifests exposed by a ManifestProvider and
providing convenient lookup APIs for:

- Backends (by id, list all)
- Resources (by id/version, list all)
- Policies (by resource id, list all)
  - MandatoryFilterPolicy: exact resource_id lookup
  - OperationalPolicy: exact resource_id lookup
  - AccessPolicy: resource_selector matching (exact or wildcard)

The goal is to keep ManifestProvider focused on *how* manifests are loaded,
and keep lookup logic here so it can be reused across different providers.
"""

from __future__ import annotations

import logging
import re
import threading
from fnmatch import fnmatch

from adp_hypervisor.manifest.physical import BackendDefinition, BackendType
from adp_hypervisor.manifest.policy import (
    AccessPolicy,
    MandatoryFilterPolicy,
    OperationalPolicy,
    Policy,
)
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.manifest.semantic import CuratedResource
from adp_hypervisor.protocol.types import Field

logger = logging.getLogger(__name__)


# Namespace and ResourceId patterns
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*:[A-Za-z0-9_-]+$")


def _is_valid_resource_selector(selector: str) -> bool:
    """Return True if selector conforms to the ResourceSelector grammar.

    Valid forms (spec: * only as the final token):
    - "*" (global catch-all)
    - "namespace:name" (exact, no wildcard)
    - "namespace:*" (all names in one namespace)
    - "namespace.*" or "namespace.sub.*" (namespace-prefix)

    Invalid: empty, "a*", "com.acme.*:name", "com.acme.*:*", multiple "*", etc.
    """
    if not selector or not selector.strip():
        return False
    s = selector.strip()
    if s == "*":
        return True
    if "*" not in s:
        return _is_valid_concrete_resource_id(s)
    if s.endswith(":*"):
        # namespace:* form – enforce exactly one colon and valid namespace.
        if s.count("*") != 1:
            return False
        if s.count(":") != 1:
            return False
        namespace, wildcard = s.split(":", 1)
        return bool(_NAMESPACE_RE.fullmatch(namespace)) and wildcard == "*"
    if s.endswith(".*"):
        if s.count("*") != 1 or ":" in s:
            return False
        # Strip the trailing ".*" and validate namespace segments.
        namespace_prefix = s[:-2]
        return bool(_NAMESPACE_RE.fullmatch(namespace_prefix))
    return False


def _is_valid_concrete_resource_id(resource_id: str) -> bool:
    """Return True if resource_id looks like a concrete ResourceId (domain:alias).

    A concrete ID must contain at least one ":" and must not contain "*".
    """
    if not resource_id or not resource_id.strip():
        return False
    s = resource_id.strip()
    if "*" in s:
        return False
    # Concrete ResourceId: namespace:name, where namespace matches _NAMESPACE_RE
    # and name (alias) contains no dots.
    return bool(_RESOURCE_ID_RE.fullmatch(s))


class ManifestIndex:
    """
    In-memory index over manifests exposed by a ManifestProvider.

    This class is intentionally stateless with respect to persistence; it
    assumes the underlying provider is responsible for loading manifests and
    simply builds indexes over the provider's current view.
    """

    def __init__(self, provider: ManifestProvider) -> None:
        self._provider = provider
        self._lock = threading.RLock()

        self._backends_by_id: dict[str, BackendDefinition] = {}
        self._resources_by_id: dict[str, list[CuratedResource]] = {}
        # Policy indexes (built from flat Policy list)
        self._mandatory_filters: dict[str, list[MandatoryFilterPolicy]] = {}
        self._operational_policies: dict[str, OperationalPolicy] = {}
        self._access_policies: list[AccessPolicy] = []
        self._indexes_built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """
        Clear cached indexes so they will be rebuilt on next access.

        Call this if the underlying provider has been re-loaded and you want
        to pick up new manifest state.
        """
        with self._lock:
            self._indexes_built = False

    # Backends ---------------------------------------------------------

    def get_backend(self, backend_id: str) -> BackendDefinition | None:
        """Get a backend definition by id."""
        self._ensure_indexes()
        return self._backends_by_id.get(backend_id)

    def list_backends(self) -> list[BackendDefinition]:
        """Return all backend definitions."""
        self._ensure_indexes()
        return list(self._backends_by_id.values())

    def inject_convention_fields(self, backend_type: BackendType, fields: list[Field]) -> None:
        """Inject convention fields into schema-less resources of a given backend type.

        For resources whose ``source_definition.fields`` is ``None`` and whose
        backend matches ``backend_type``, this method sets the fields to the
        provided convention field list.  Resources that already declare fields
        are not modified.

        Args:
            backend_type: The backend type to match (e.g. ``BackendType.BLOB_STORAGE``).
            fields: The convention fields to inject.
        """
        self._ensure_indexes()
        injected = 0
        for versions in self._resources_by_id.values():
            for resource in versions:
                if resource.source_definition.fields is not None:
                    continue
                backend_def = self._backends_by_id.get(resource.backend_id)
                if backend_def is None or backend_def.type != backend_type:
                    continue
                resource.source_definition.fields = list(fields)
                injected += 1

        if injected:
            logger.info(
                "Injected %d convention fields into %d schema-less %s resources",
                len(fields),
                injected,
                backend_type.value,
            )

    # Resources --------------------------------------------------------

    def list_resources(self) -> list[CuratedResource]:
        """Return all curated resources (all versions)."""
        self._ensure_indexes()
        result: list[CuratedResource] = []
        for versions in self._resources_by_id.values():
            result.extend(versions)
        return result

    def get_resource(self, resource_id: str, version: int | None = None) -> CuratedResource | None:
        """
        Get a resource by id and optional version.

        If version is None, returns the latest version (highest numeric version).
        """
        self._ensure_indexes()
        versions = self._resources_by_id.get(resource_id)
        if not versions:
            return None

        if version is not None:
            for r in versions:
                if r.version == version:
                    return r
            return None

        # Return the latest version (highest version number)
        return max(versions, key=lambda r: r.version or 1)

    # Policies ---------------------------------------------------------

    def list_policies(self) -> list[Policy]:
        """Return all policies (all types)."""
        self._ensure_indexes()
        result: list[Policy] = []
        # Mandatory filters (grouped by resource_id, preserve per-resource order)
        for policies in self._mandatory_filters.values():
            result.extend(policies)
        # Operational policies
        result.extend(self._operational_policies.values())
        # Access policies
        result.extend(self._access_policies)
        return result

    def get_mandatory_filter_policies(self, resource_id: str) -> list[MandatoryFilterPolicy]:
        """Return all MANDATORY_FILTER policies for an exact resource_id."""
        self._ensure_indexes()
        return list(self._mandatory_filters.get(resource_id, []))

    def get_operational_policy(self, resource_id: str) -> OperationalPolicy | None:
        """Return the OPERATIONAL policy for an exact resource_id, or None."""
        self._ensure_indexes()
        return self._operational_policies.get(resource_id)

    def get_access_policy(self, resource_id: str) -> AccessPolicy | None:
        """
        Return the most-specific ACCESS policy whose resource_selector matches resource_id.

        Specificity ranking (highest to lowest):
        1. Exact ``namespace:name``
        2. Exact-namespace wildcard ``namespace:*``
        3. Namespace-prefix forms ``namespace.*`` / ``namespace.sub.*``
           (longer namespace = more specific)

        When multiple policies share the same highest specificity, the first
        one encountered in manifest order is returned.  Callers that need
        union-merge semantics should use ``get_access_policies_for_resource``
        instead.

        Returns None if no ACCESS policy selector matches resource_id.
        """
        self._ensure_indexes()
        candidates = self._resolve_access_policies(resource_id)
        return candidates[0] if candidates else None

    def get_access_policies_for_resource(self, resource_id: str) -> list[AccessPolicy]:
        """
        Return all ACCESS policies at the highest specificity for resource_id.

        See ``get_access_policy`` for specificity ranking rules.
        """
        self._ensure_indexes()
        return self._resolve_access_policies(resource_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """
        Ensure that indexes are built.

        Assumes the underlying provider has already been loaded; if it is not
        loaded, provider.get_*_manifest() may raise (e.g. RuntimeError).
        """
        if self._indexes_built:
            return

        # Double-checked locking so multiple threads can race safely to build
        with self._lock:
            if self._indexes_built:
                return

            physical = self._provider.get_physical_manifest()
            semantic = self._provider.get_semantic_manifest()
            policy = self._provider.get_policy_manifest()

            backends_by_id: dict[str, BackendDefinition] = {b.id: b for b in physical.backends}

            resources_by_id: dict[str, list[CuratedResource]] = {}
            for r in semantic.resources or []:
                rid = r.resource_id
                if rid is None:
                    continue
                resources_by_id.setdefault(rid, []).append(r)

            mandatory_filters: dict[str, list[MandatoryFilterPolicy]] = {}
            operational_policies: dict[str, OperationalPolicy] = {}
            access_policies: list[AccessPolicy] = []

            for p in policy.policies or []:
                if isinstance(p, MandatoryFilterPolicy):
                    mandatory_filters.setdefault(p.resource_id, []).append(p)
                elif isinstance(p, OperationalPolicy):
                    # Last OPERATIONAL policy for a given resource_id wins.
                    operational_policies[p.resource_id] = p
                elif isinstance(p, AccessPolicy):
                    if not _is_valid_resource_selector(p.resource_selector):
                        logger.warning(
                            "Skipping ACCESS policy with invalid resourceSelector %r",
                            p.resource_selector,
                        )
                        continue
                    access_policies.append(p)

            # Atomically swap references
            self._backends_by_id = backends_by_id
            self._resources_by_id = resources_by_id
            self._mandatory_filters = mandatory_filters
            self._operational_policies = operational_policies
            self._access_policies = access_policies
            self._indexes_built = True

            logger.debug(
                "ManifestIndex built: %d backends, %d resources, "
                "%d mandatory-filter policies, %d operational policies, %d access policies",
                len(self._backends_by_id),
                len(self._resources_by_id),
                sum(len(v) for v in self._mandatory_filters.values()),
                len(self._operational_policies),
                len(self._access_policies),
            )

    def _selector_specificity(self, selector: str) -> tuple[int, int]:
        """
        Return a comparable specificity score for an ACCESS selector.

        Higher tuple = more specific. Invalid selectors return (0, 0) so they
        never win. Callers should pair this with _selector_matches, which
        returns False for invalid selectors.

        Args:
            selector: A ResourceSelector string.

        Returns:
            A tuple ``(rank, detail)`` where higher values are more specific.
        """
        if not _is_valid_resource_selector(selector):
            return (0, 0)
        s = selector.strip()
        if "*" not in s:
            return (3, 0)
        if s == "*":
            return (0, 0)
        if s.endswith(":*"):
            return (2, 0)
        namespace_part = s[:-2]
        return (1, len(namespace_part))

    def _selector_matches(self, selector: str, resource_id: str) -> bool:
        """
        Return True if selector matches resource_id.

        Invalid selector or invalid resource_id (e.g. empty, contains "*")
        yields False. This avoids undefined behavior and treats bad data as
        non-matching.

        Args:
            selector: A ResourceSelector string.
            resource_id: A concrete ResourceId (no wildcards).

        Returns:
            True if the selector matches the resource_id.
        """
        if not _is_valid_resource_selector(selector) or not _is_valid_concrete_resource_id(
            resource_id
        ):
            return False
        s = selector.strip()
        rid = resource_id.strip()
        if "*" not in s:
            return s == rid
        if s == "*":
            return True
        if s.endswith(":*"):
            namespace = s[:-2]
            return rid.startswith(namespace + ":")
        if s.endswith(".*"):
            prefix = s[:-1]
            return fnmatch(rid, prefix + "*")
        return fnmatch(rid, s)

    def _resolve_access_policies(self, resource_id: str) -> list[AccessPolicy]:
        """
        Return the most-specific matching ACCESS policies for resource_id.

        Args:
            resource_id: The concrete resource ID to resolve.

        Returns:
            List of ACCESS policies at the highest specificity, in manifest order.
        """
        matches = [
            (self._selector_specificity(p.resource_selector), p)
            for p in self._access_policies
            if self._selector_matches(p.resource_selector, resource_id)
        ]
        if not matches:
            return []
        max_specificity = max(s for s, _ in matches)
        return [p for s, p in matches if s == max_specificity]


# =============================================================================
# Global ManifestIndex registry (for backends that need manifest lookups)
# =============================================================================

_GLOBAL_MANIFEST_INDEX: ManifestIndex | None = None


def set_global_manifest_index(index: ManifestIndex | None) -> None:
    """Set the process-wide ManifestIndex used by backends.

    Passing None clears the global index.
    """
    global _GLOBAL_MANIFEST_INDEX
    _GLOBAL_MANIFEST_INDEX = index


def get_global_manifest_index() -> ManifestIndex:
    """Return the process-wide ManifestIndex.

    Raises:
        RuntimeError: If the global ManifestIndex has not been configured.
    """
    if _GLOBAL_MANIFEST_INDEX is None:
        raise RuntimeError("Global ManifestIndex has not been configured")
    return _GLOBAL_MANIFEST_INDEX
