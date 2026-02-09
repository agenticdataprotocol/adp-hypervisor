"""
YAML-based ManifestProvider implementation.

Loads physical, semantic, and policy manifests from YAML files. Higher-level
lookup APIs (backends, resources, policies) are provided by helper classes
such as ManifestIndex that consume this provider.
"""

import logging
from pathlib import Path

import yaml

from adp_hypervisor.manifest.physical import PhysicalManifest
from adp_hypervisor.manifest.policy import PolicyManifest
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.manifest.semantic import SemanticManifest

logger = logging.getLogger(__name__)


class YamlManifestProvider(ManifestProvider):
    """
    YAML-based manifest provider.

    Responsible only for loading and exposing the three manifest models; it
    does not implement lookup/indexing logic.
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

    def load(self) -> None:
        """Load all three manifests from YAML files."""
        self._physical = self._load_physical()
        self._semantic = self._load_semantic()
        self._policy = self._load_policy()
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
