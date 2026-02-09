"""
Physical Manifest models.

Defines the types for the ADP Curation Plane's physical layer,
which describes backend data sources and their connection details.
Based on the PhysicalManifest section of curation.ts.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import ConfigDict
from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import ADPModel


class BackendType(StrEnum):
    """Supported backend types for physical data sources."""

    RDBMS = "RDBMS"
    VECTOR = "VECTOR"
    S3 = "S3"
    NOSQL = "NOSQL"
    GRAPH = "GRAPH"


class CredentialReference(ADPModel):
    """
    Reference to credentials stored externally.

    Supports environment variables, secret managers, and file-based credentials.
    """

    type: Literal["env", "secret", "file"] = PydanticField(
        ..., description="Type of credential reference"
    )
    key: str = PydanticField(..., description="The key or path to the credential")
    manager: str | None = PydanticField(
        default=None, description="Secret manager identifier (required when type is 'secret')"
    )


class RDBMSBackendConfig(ADPModel):
    """Configuration for RDBMS backend types."""

    type: Literal["RDBMS"] = PydanticField(default="RDBMS", description="Backend type")
    uri: str = PydanticField(..., description="Connection URI for the database")
    schema_name: str | None = PydanticField(
        default=None, alias="schema", description="Database schema name"
    )
    properties: dict[str, Any] | None = PydanticField(
        default=None, description="Additional RDBMS properties"
    )


class VectorBackendConfig(ADPModel):
    """Configuration for Vector backend types."""

    type: Literal["VECTOR"] = PydanticField(default="VECTOR", description="Backend type")
    provider: str = PydanticField(..., description="Vector database provider")
    index_name: str = PydanticField(..., description="Index or collection name")
    endpoint: str | None = PydanticField(default=None, description="API endpoint")
    dimensions: int | None = PydanticField(default=None, description="Vector dimensions")


class S3BackendConfig(ADPModel):
    """Configuration for S3 backend types."""

    type: Literal["S3"] = PydanticField(default="S3", description="Backend type")
    uri: str = PydanticField(..., description="S3 bucket URI")
    region: str = PydanticField(..., description="AWS region or equivalent")
    endpoint: str | None = PydanticField(
        default=None, description="Endpoint URL for S3-compatible services"
    )


class NOSQLBackendConfig(ADPModel):
    """Configuration for NoSQL backend types."""

    model_config = ConfigDict(extra="allow")

    type: Literal["NOSQL"] = PydanticField(default="NOSQL", description="Backend type")


class GraphBackendConfig(ADPModel):
    """Configuration for Graph backend types."""

    model_config = ConfigDict(extra="allow")

    type: Literal["GRAPH"] = PydanticField(default="GRAPH", description="Backend type")


BackendConfig = Annotated[
    RDBMSBackendConfig
    | VectorBackendConfig
    | S3BackendConfig
    | NOSQLBackendConfig
    | GraphBackendConfig,
    PydanticField(discriminator="type"),
]
"""Backend-specific configuration, discriminated by type."""


class Backend(ADPModel):
    """Definition of a physical backend data source."""

    id: str = PydanticField(..., description="Unique identifier for this backend")
    type: BackendType = PydanticField(..., description="Type of backend")
    config: BackendConfig = PydanticField(..., description="Backend-specific configuration")
    credentials: CredentialReference | None = PydanticField(
        default=None, description="Credential reference for authentication"
    )
    metadata: dict[str, Any] | None = PydanticField(
        default=None, description="Additional metadata about the backend"
    )


class PhysicalManifest(ADPModel):
    """Root structure for the physical manifest (physical.yaml)."""

    version: str = PydanticField(..., description="Version of the manifest schema")
    backends: list[Backend] = PydanticField(..., description="List of backend definitions")
