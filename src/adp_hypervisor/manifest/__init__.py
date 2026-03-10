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
