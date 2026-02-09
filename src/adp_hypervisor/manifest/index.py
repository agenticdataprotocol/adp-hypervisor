"""
High-level manifest query helper built on top of ManifestProvider.

This class is responsible for building in-memory indexes over the raw
Physical/Semantic/Policy manifests exposed by a ManifestProvider and
providing convenient lookup APIs for:

- Backends (by id, list all)
- Resources (by id/version, list all)
- Policies (by resource id, list all, wildcard matching)

The goal is to keep ManifestProvider focused on *how* manifests are loaded,
and keep lookup logic here so it can be reused across different providers.
"""

from __future__ import annotations

import logging
import threading
from fnmatch import fnmatch

from adp_hypervisor.manifest.physical import Backend
from adp_hypervisor.manifest.policy import ResourcePolicy
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.manifest.semantic import CuratedResource

logger = logging.getLogger(__name__)


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

        self._backends_by_id: dict[str, Backend] = {}
        self._resources_by_id: dict[str, list[CuratedResource]] = {}
        self._policies_by_id: dict[str, ResourcePolicy] = {}
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

    def get_backend(self, backend_id: str) -> Backend | None:
        """Get a backend definition by id."""
        self._ensure_indexes()
        return self._backends_by_id.get(backend_id)

    def list_backends(self) -> list[Backend]:
        """Return all backend definitions."""
        self._ensure_indexes()
        return list(self._backends_by_id.values())

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

    def get_policy(self, resource_id: str) -> ResourcePolicy | None:
        """
        Get the policy for a resource.

        Performs exact match first, then wildcard match (e.g. "com.acme.finance:*").
        """
        self._ensure_indexes()

        # Exact match
        policy = self._policies_by_id.get(resource_id)
        if policy is not None:
            return policy

        # Wildcard match
        for pattern, p in self._policies_by_id.items():
            if "*" in pattern and fnmatch(resource_id, pattern):
                return p
        return None

    def list_policies(self) -> list[ResourcePolicy]:
        """Return all resource policies."""
        self._ensure_indexes()
        return list(self._policies_by_id.values())

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

            # Build new indexes in local variables so readers never see
            # partially-populated dictionaries.
            backends_by_id: dict[str, Backend] = {b.id: b for b in physical.backends}

            resources_by_id: dict[str, list[CuratedResource]] = {}
            for r in semantic.resources or []:
                rid = r.resource_id
                if rid is None:
                    continue
                resources_by_id.setdefault(rid, []).append(r)

            policies_by_id: dict[str, ResourcePolicy] = {}
            for p in policy.policies or []:
                policies_by_id[p.resource_id] = p

            # Atomically swap references
            self._backends_by_id = backends_by_id
            self._resources_by_id = resources_by_id
            self._policies_by_id = policies_by_id
            self._indexes_built = True

            logger.debug(
                "ManifestIndex built: %d backends, %d resources, %d policies",
                len(self._backends_by_id),
                len(self._resources_by_id),
                len(self._policies_by_id),
            )
