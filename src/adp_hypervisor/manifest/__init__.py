"""ADP Curation Manifest models and providers."""

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import (
    BackendConfig,
    BackendDefinition,
    BackendProvider,
    BackendType,
    BlobStorageBackendConfig,
    CredentialReference,
    GraphBackendConfig,
    NOSQLBackendConfig,
    PhysicalManifest,
    RDBMSBackendConfig,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.policy import (
    AccessPolicy,
    MandatoryFilterPolicy,
    OperationalPolicy,
    Policy,
    PolicyCondition,
    PolicyManifest,
    ResourceSelector,
    RoleAccessEntry,
)
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.manifest.semantic import (
    CuratedResource,
    SemanticManifest,
    SourceDefinition,
)
from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.protocol.types import LATEST_PROTOCOL_VERSION as _LATEST_PROTOCOL_VERSION

LATEST_MANIFEST_SCHEMA_VERSION = _LATEST_PROTOCOL_VERSION

__all__ = [
    # Versioning
    "LATEST_MANIFEST_SCHEMA_VERSION",
    # Provider / Index
    "ManifestProvider",
    "ManifestIndex",
    "YamlManifestProvider",
    # Physical
    "BackendType",
    "BackendProvider",
    "CredentialReference",
    "RDBMSBackendConfig",
    "VectorBackendConfig",
    "BlobStorageBackendConfig",
    "NOSQLBackendConfig",
    "GraphBackendConfig",
    "BackendDefinition",
    "BackendConfig",
    "PhysicalManifest",
    # Semantic
    "SourceDefinition",
    "CuratedResource",
    "SemanticManifest",
    # Policy
    "PolicyCondition",
    "ResourceSelector",
    "MandatoryFilterPolicy",
    "OperationalPolicy",
    "RoleAccessEntry",
    "AccessPolicy",
    "Policy",
    "PolicyManifest",
]
