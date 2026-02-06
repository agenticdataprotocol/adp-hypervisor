"""Tests for Physical Manifest models."""

import pytest

from adp_hypervisor.manifest.physical import (
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

# =============================================================================
# CredentialReference Tests
# =============================================================================


class TestCredentialReference:
    def test_env_credential(self) -> None:
        cred = CredentialReference(type="env", key="DB_PASSWORD")
        assert cred.type == "env"
        assert cred.key == "DB_PASSWORD"
        assert cred.manager is None

    def test_secret_credential(self) -> None:
        cred = CredentialReference(
            type="secret", key="production/db-credentials", manager="AWS_SECRETS_MANAGER"
        )
        assert cred.type == "secret"
        assert cred.manager == "AWS_SECRETS_MANAGER"

    def test_file_credential(self) -> None:
        cred = CredentialReference(type="file", key="/etc/secrets/db-password.txt")
        assert cred.type == "file"

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValueError):
            CredentialReference(type="invalid", key="key")  # type: ignore[arg-type]


# =============================================================================
# Backend Config Tests
# =============================================================================


class TestBackendConfigs:
    def test_rdbms_config(self) -> None:
        config = RDBMSBackendConfig.model_validate(
            {"type": "RDBMS", "uri": "postgresql://localhost:5432/db", "schema": "public"}
        )
        assert config.type == "RDBMS"
        assert config.uri == "postgresql://localhost:5432/db"
        assert config.schema_name == "public"

    def test_rdbms_config_with_properties(self) -> None:
        config = RDBMSBackendConfig(uri="postgresql://localhost/db", properties={"pool_size": 10})
        assert config.properties == {"pool_size": 10}

    def test_vector_config(self) -> None:
        config = VectorBackendConfig.model_validate(
            {
                "type": "VECTOR",
                "provider": "PINECONE",
                "indexName": "my-index",
                "endpoint": "https://api.pinecone.io",
                "dimensions": 1536,
            }
        )
        assert config.provider == "PINECONE"
        assert config.index_name == "my-index"
        assert config.dimensions == 1536

    def test_s3_config(self) -> None:
        config = S3BackendConfig.model_validate(
            {"type": "S3", "uri": "s3://my-bucket/", "region": "us-east-1"}
        )
        assert config.uri == "s3://my-bucket/"
        assert config.region == "us-east-1"

    def test_nosql_config_extra_fields(self) -> None:
        config = NOSQLBackendConfig.model_validate(
            {"type": "NOSQL", "uri": "mongodb://localhost:27017/db"}
        )
        assert config.type == "NOSQL"

    def test_graph_config_extra_fields(self) -> None:
        config = GraphBackendConfig.model_validate(
            {"type": "GRAPH", "uri": "neo4j://localhost:7687"}
        )
        assert config.type == "GRAPH"


# =============================================================================
# BackendDefinition Tests
# =============================================================================


class TestBackendDefinition:
    def test_rdbms_backend(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "finance_sql",
                "type": "RDBMS",
                "config": {
                    "type": "RDBMS",
                    "uri": "postgresql://localhost:5432/finance",
                },
                "credentials": {"type": "env", "key": "DB_PASS"},
            }
        )
        assert backend.id == "finance_sql"
        assert backend.type == BackendType.RDBMS
        assert isinstance(backend.config, RDBMSBackendConfig)
        assert backend.credentials is not None
        assert backend.credentials.type == "env"

    def test_vector_backend(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "vectors",
                "type": "VECTOR",
                "config": {
                    "type": "VECTOR",
                    "provider": "PINECONE",
                    "indexName": "idx",
                },
            }
        )
        assert backend.type == BackendType.VECTOR
        assert isinstance(backend.config, VectorBackendConfig)
        assert backend.credentials is None

    def test_backend_with_metadata(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "db",
                "type": "RDBMS",
                "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                "metadata": {"region": "us-east-1"},
            }
        )
        assert backend.metadata == {"region": "us-east-1"}


# =============================================================================
# PhysicalManifest Tests
# =============================================================================


class TestPhysicalManifest:
    def test_parse_full_manifest(self) -> None:
        manifest = PhysicalManifest.model_validate(
            {
                "version": "1.0.0",
                "backends": [
                    {
                        "id": "db1",
                        "type": "RDBMS",
                        "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                    },
                    {
                        "id": "vec1",
                        "type": "VECTOR",
                        "config": {
                            "type": "VECTOR",
                            "provider": "PINECONE",
                            "indexName": "idx",
                        },
                    },
                ],
            }
        )
        assert manifest.version == "1.0.0"
        assert len(manifest.backends) == 2
        assert isinstance(manifest.backends[0].config, RDBMSBackendConfig)
        assert isinstance(manifest.backends[1].config, VectorBackendConfig)

    def test_serialization_round_trip(self) -> None:
        data = {
            "version": "1.0.0",
            "backends": [
                {
                    "id": "s3",
                    "type": "S3",
                    "config": {"type": "S3", "uri": "s3://bucket/", "region": "us-east-1"},
                }
            ],
        }
        manifest = PhysicalManifest.model_validate(data)
        dumped = manifest.model_dump(by_alias=True, exclude_none=True)
        assert dumped["backends"][0]["config"]["uri"] == "s3://bucket/"

    def test_all_backend_types(self) -> None:
        """Verify all 5 backend types can be parsed."""
        manifest = PhysicalManifest.model_validate(
            {
                "version": "1.0.0",
                "backends": [
                    {
                        "id": "b1",
                        "type": "RDBMS",
                        "config": {"type": "RDBMS", "uri": "pg://localhost/db"},
                    },
                    {
                        "id": "b2",
                        "type": "VECTOR",
                        "config": {"type": "VECTOR", "provider": "P", "indexName": "i"},
                    },
                    {
                        "id": "b3",
                        "type": "S3",
                        "config": {"type": "S3", "uri": "s3://b/", "region": "us"},
                    },
                    {
                        "id": "b4",
                        "type": "NOSQL",
                        "config": {"type": "NOSQL", "uri": "mongo://localhost"},
                    },
                    {
                        "id": "b5",
                        "type": "GRAPH",
                        "config": {"type": "GRAPH", "uri": "neo4j://localhost"},
                    },
                ],
            }
        )
        assert len(manifest.backends) == 5
        types = [b.type for b in manifest.backends]
        assert set(types) == {
            BackendType.RDBMS,
            BackendType.VECTOR,
            BackendType.S3,
            BackendType.NOSQL,
            BackendType.GRAPH,
        }
