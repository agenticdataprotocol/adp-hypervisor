"""
YAML-based ManifestProvider implementation.

Loads physical, semantic, and policy manifests from YAML files
and provides in-memory lookup APIs.
"""

import logging
from fnmatch import fnmatch
from pathlib import Path

import yaml

from adp_hypervisor.manifest.base import ManifestProvider
from adp_hypervisor.manifest.physical import BackendDefinition, PhysicalManifest
from adp_hypervisor.manifest.policy import PolicyManifest, ResourcePolicy
from adp_hypervisor.manifest.semantic import CuratedResource, SemanticManifest

logger = logging.getLogger(__name__)


class YamlManifestProvider(ManifestProvider):
    """
    YAML-based manifest provider.

    Loads manifests from YAML files and provides in-memory lookup.
    """

    def __init__(
        self,
        physical_path: str | Path,
        semantic_path: str | Path,
        policy_path: str | Path,
    ) -> None:
        self._physical_path = Path(physical_path)
        self._semantic_path = Path(semantic_path)
        self._policy_path = Path(policy_path)

        self._physical: PhysicalManifest | None = None
        self._semantic: SemanticManifest | None = None
        self._policy: PolicyManifest | None = None

        # Indexes built after loading
        self._backends_by_id: dict[str, BackendDefinition] = {}
        self._resources_by_id: dict[str, list[CuratedResource]] = {}
        self._policies_by_id: dict[str, ResourcePolicy] = {}

    def load(self) -> None:
        """Load all three manifests from YAML files and build indexes."""
        self._physical = self._load_physical()
        self._semantic = self._load_semantic()
        self._policy = self._load_policy()
        self._build_indexes()
        logger.info("Manifests loaded successfully")

    def get_physical_manifest(self) -> PhysicalManifest:
        self._ensure_loaded()
        assert self._physical is not None
        return self._physical

    def get_semantic_manifest(self) -> SemanticManifest:
        self._ensure_loaded()
        assert self._semantic is not None
        return self._semantic

    def get_policy_manifest(self) -> PolicyManifest:
        self._ensure_loaded()
        assert self._policy is not None
        return self._policy

    def get_backend(self, backend_id: str) -> BackendDefinition | None:
        self._ensure_loaded()
        return self._backends_by_id.get(backend_id)

    def list_backends(self) -> list[BackendDefinition]:
        self._ensure_loaded()
        return list(self._backends_by_id.values())

    def list_resources(self) -> list[CuratedResource]:
        self._ensure_loaded()
        result: list[CuratedResource] = []
        for versions in self._resources_by_id.values():
            result.extend(versions)
        return result

    def get_resource(self, resource_id: str, version: int | None = None) -> CuratedResource | None:
        self._ensure_loaded()
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

    def get_policy(self, resource_id: str) -> ResourcePolicy | None:
        self._ensure_loaded()
        # Exact match first
        policy = self._policies_by_id.get(resource_id)
        if policy is not None:
            return policy

        # Wildcard match (e.g. "com.acme.finance:*")
        for pattern, p in self._policies_by_id.items():
            if "*" in pattern and fnmatch(resource_id, pattern):
                return p
        return None

    def list_policies(self) -> list[ResourcePolicy]:
        self._ensure_loaded()
        return list(self._policies_by_id.values())

    def _ensure_loaded(self) -> None:
        if self._physical is None or self._semantic is None or self._policy is None:
            raise RuntimeError("Manifests not loaded; call load() first")

    def _load_yaml(self, path: Path) -> dict:  # type: ignore[type-arg]
        """Load and parse a YAML file."""
        logger.debug("Loading YAML: %s", path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
        return data

    def _load_physical(self) -> PhysicalManifest:
        data = self._load_yaml(self._physical_path)
        return PhysicalManifest.model_validate(data)

    def _load_semantic(self) -> SemanticManifest:
        data = self._load_yaml(self._semantic_path)
        return SemanticManifest.model_validate(data)

    def _load_policy(self) -> PolicyManifest:
        data = self._load_yaml(self._policy_path)
        return PolicyManifest.model_validate(data)

    def _build_indexes(self) -> None:
        """Build lookup indexes from loaded manifests."""
        assert self._physical is not None
        assert self._semantic is not None
        assert self._policy is not None

        # Index backends by id
        self._backends_by_id = {b.id: b for b in self._physical.backends}

        # Index resources by resourceId, grouped by version
        self._resources_by_id = {}
        for r in self._semantic.resources or []:
            rid = r.resource_id
            if rid is None:
                continue
            self._resources_by_id.setdefault(rid, []).append(r)

        # Index policies by resourceId
        self._policies_by_id = {}
        for p in self._policy.policies or []:
            self._policies_by_id[p.resource_id] = p

        logger.debug(
            "Indexes built: %d backends, %d resources, %d policies",
            len(self._backends_by_id),
            len(self._resources_by_id),
            len(self._policies_by_id),
        )
