"""ADP Curation Manifest models and providers."""

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import (
    BackendConfig,
    BackendDefinition,
    BackendType,
    CredentialReference,
    GraphBackendConfig,
    NOSQLBackendConfig,
    PhysicalManifest,
    RDBMSBackendConfig,
    S3BackendConfig,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.policy import (
    MandatoryFilterRule,
    OperationalRule,
    PolicyCondition,
    PolicyManifest,
    PolicyRule,
    ResourcePolicy,
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
    "CredentialReference",
    "RDBMSBackendConfig",
    "VectorBackendConfig",
    "S3BackendConfig",
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
    "MandatoryFilterRule",
    "OperationalRule",
    "PolicyRule",
    "ResourcePolicy",
    "PolicyManifest",
]
