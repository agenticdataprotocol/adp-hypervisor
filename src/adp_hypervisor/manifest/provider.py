"""
ManifestProvider abstract base class.

Defines the abstract interface for loading ADP curation manifests and returning
the raw manifest models. Higher-level query operations (backends, resources,
policies) are implemented separately in helper classes that consume this
interface.
"""

from abc import ABC, abstractmethod

from adp_hypervisor.manifest.physical import PhysicalManifest
from adp_hypervisor.manifest.policy import PolicyManifest
from adp_hypervisor.manifest.semantic import SemanticManifest


class ManifestProvider(ABC):
    """
    Abstract interface for manifest providers.

    Implementations know *how* to load Physical, Semantic, and Policy manifests
    from a particular storage backend (YAML files, database, HTTP, etc.).

    They do not perform query/indexing logic themselves; that is delegated to
    higher-level helper classes that consume this interface.
    """

    @abstractmethod
    def load(self) -> None:
        """Load all manifests from the underlying storage."""

    @abstractmethod
    def get_physical_manifest(self) -> PhysicalManifest:
        """Return the loaded physical manifest."""

    @abstractmethod
    def get_semantic_manifest(self) -> SemanticManifest:
        """Return the loaded semantic manifest."""

    @abstractmethod
    def get_policy_manifest(self) -> PolicyManifest:
        """Return the loaded policy manifest."""
