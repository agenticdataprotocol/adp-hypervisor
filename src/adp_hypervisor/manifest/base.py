"""
ManifestProvider abstract base class.

Defines the abstract interface for loading and querying ADP curation manifests.
"""

from abc import ABC, abstractmethod

from adp_hypervisor.manifest.physical import BackendDefinition, PhysicalManifest
from adp_hypervisor.manifest.policy import PolicyManifest, ResourcePolicy
from adp_hypervisor.manifest.semantic import CuratedResource, SemanticManifest


class ManifestProvider(ABC):
    """
    Abstract interface for manifest operations.

    Provides access to the three-layered manifest strategy:
    Physical, Semantic, and Policy manifests.
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

    @abstractmethod
    def get_backend(self, backend_id: str) -> BackendDefinition | None:
        """
        Get a backend definition by ID.

        Args:
            backend_id: The unique backend identifier.

        Returns:
            The backend definition, or None if not found.
        """

    @abstractmethod
    def list_backends(self) -> list[BackendDefinition]:
        """Return all backend definitions."""

    @abstractmethod
    def list_resources(self) -> list[CuratedResource]:
        """Return all curated resources."""

    @abstractmethod
    def get_resource(self, resource_id: str, version: int | None = None) -> CuratedResource | None:
        """
        Get a resource by ID and optional version.

        Args:
            resource_id: The resource identifier.
            version: Optional version number. If None, returns the latest version.

        Returns:
            The curated resource, or None if not found.
        """

    @abstractmethod
    def get_policy(self, resource_id: str) -> ResourcePolicy | None:
        """
        Get the policy for a resource.

        Args:
            resource_id: The resource identifier.

        Returns:
            The resource policy, or None if no policy is defined.
        """

    @abstractmethod
    def list_policies(self) -> list[ResourcePolicy]:
        """Return all resource policies."""
