"""Tests for Physical Manifest models."""

import unittest

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendProvider,
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


class TestCredentialReference(unittest.TestCase):
    def test_env_credential(self) -> None:
        cred = CredentialReference(type="env", key="DB_PASSWORD")
        self.assertEqual(cred.type, "env")
        self.assertEqual(cred.key, "DB_PASSWORD")
        self.assertIsNone(cred.manager)

    def test_secret_credential(self) -> None:
        cred = CredentialReference(
            type="secret", key="production/db-credentials", manager="AWS_SECRETS_MANAGER"
        )
        self.assertEqual(cred.type, "secret")
        self.assertEqual(cred.manager, "AWS_SECRETS_MANAGER")

    def test_file_credential(self) -> None:
        cred = CredentialReference(type="file", key="/etc/secrets/db-password.txt")
        self.assertEqual(cred.type, "file")

    def test_invalid_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CredentialReference(type="invalid", key="key")  # type: ignore[arg-type]


# =============================================================================
# Backend Config Tests
# =============================================================================


class TestBackendConfigs(unittest.TestCase):
    def test_rdbms_config(self) -> None:
        config = RDBMSBackendConfig.model_validate(
            {"type": "RDBMS", "uri": "postgresql://localhost:5432/db", "schema": "public"}
        )
        self.assertEqual(config.type, "RDBMS")
        self.assertEqual(config.uri, "postgresql://localhost:5432/db")
        self.assertEqual(config.schema_name, "public")

    def test_rdbms_config_with_properties(self) -> None:
        config = RDBMSBackendConfig(uri="postgresql://localhost/db", properties={"pool_size": 10})
        self.assertEqual(config.properties, {"pool_size": 10})

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
        self.assertEqual(config.provider, "PINECONE")
        self.assertEqual(config.index_name, "my-index")
        self.assertEqual(config.dimensions, 1536)

    def test_s3_config(self) -> None:
        config = S3BackendConfig.model_validate(
            {"type": "S3", "uri": "s3://my-bucket/", "region": "us-east-1"}
        )
        self.assertEqual(config.uri, "s3://my-bucket/")
        self.assertEqual(config.region, "us-east-1")

    def test_nosql_config_extra_fields(self) -> None:
        config = NOSQLBackendConfig.model_validate(
            {"type": "NOSQL", "uri": "mongodb://localhost:27017/db"}
        )
        self.assertEqual(config.type, "NOSQL")

    def test_graph_config_extra_fields(self) -> None:
        config = GraphBackendConfig.model_validate(
            {"type": "GRAPH", "uri": "neo4j://localhost:7687"}
        )
        self.assertEqual(config.type, "GRAPH")


# =============================================================================
# Backend Tests
# =============================================================================


class TestBackend(unittest.TestCase):
    def test_rdbms_backend(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "finance_sql",
                "type": "RDBMS",
                "provider": "postgresql",
                "config": {
                    "type": "RDBMS",
                    "uri": "postgresql://localhost:5432/finance",
                },
                "credentials": {"type": "env", "key": "DB_PASS"},
            }
        )
        self.assertEqual(backend.id, "finance_sql")
        self.assertEqual(backend.type, BackendType.RDBMS)
        self.assertEqual(backend.provider, "postgresql")
        self.assertIsInstance(backend.config, RDBMSBackendConfig)
        self.assertIsNotNone(backend.credentials)
        self.assertEqual(backend.credentials.type, "env")

    def test_vector_backend(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "vectors",
                "type": "VECTOR",
                "provider": "pinecone",
                "config": {
                    "type": "VECTOR",
                    "provider": "PINECONE",
                    "indexName": "idx",
                },
            }
        )
        self.assertEqual(backend.type, BackendType.VECTOR)
        self.assertEqual(backend.provider, "pinecone")
        self.assertIsInstance(backend.config, VectorBackendConfig)
        self.assertIsNone(backend.credentials)

    def test_backend_with_metadata(self) -> None:
        backend = BackendDefinition.model_validate(
            {
                "id": "db",
                "type": "RDBMS",
                "provider": "postgresql",
                "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                "metadata": {"region": "us-east-1"},
            }
        )
        self.assertEqual(backend.metadata, {"region": "us-east-1"})

    def test_provider_is_required(self) -> None:
        """provider field is required; omitting it raises a validation error."""
        with self.assertRaises(ValueError):
            BackendDefinition.model_validate(
                {
                    "id": "db",
                    "type": "RDBMS",
                    "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                }
            )

    def test_provider_type_alias(self) -> None:
        """BackendProvider is a string type alias used for provider field."""
        self.assertIs(BackendProvider, str)

    def test_field_order(self) -> None:
        """Fields should follow spec order: id, type, provider, config, ..."""
        field_names = list(BackendDefinition.model_fields.keys())
        idx_type = field_names.index("type")
        idx_provider = field_names.index("provider")
        idx_config = field_names.index("config")
        self.assertLess(idx_type, idx_provider)
        self.assertLess(idx_provider, idx_config)


# =============================================================================
# PhysicalManifest Tests
# =============================================================================


class TestPhysicalManifest(unittest.TestCase):
    def test_parse_full_manifest(self) -> None:
        manifest = PhysicalManifest.model_validate(
            {
                "version": "1.0.0",
                "backends": [
                    {
                        "id": "db1",
                        "type": "RDBMS",
                        "provider": "postgresql",
                        "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                    },
                    {
                        "id": "vec1",
                        "type": "VECTOR",
                        "provider": "pinecone",
                        "config": {
                            "type": "VECTOR",
                            "provider": "PINECONE",
                            "indexName": "idx",
                        },
                    },
                ],
            }
        )
        self.assertEqual(manifest.version, "1.0.0")
        self.assertEqual(len(manifest.backends), 2)
        self.assertIsInstance(manifest.backends[0].config, RDBMSBackendConfig)
        self.assertIsInstance(manifest.backends[1].config, VectorBackendConfig)

    def test_serialization_round_trip(self) -> None:
        data = {
            "version": "1.0.0",
            "backends": [
                {
                    "id": "s3",
                    "type": "S3",
                    "provider": "s3",
                    "config": {"type": "S3", "uri": "s3://bucket/", "region": "us-east-1"},
                }
            ],
        }
        manifest = PhysicalManifest.model_validate(data)
        dumped = manifest.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(dumped["backends"][0]["config"]["uri"], "s3://bucket/")
        self.assertEqual(dumped["backends"][0]["provider"], "s3")

    def test_all_backend_types(self) -> None:
        """Verify all 5 backend types can be parsed."""
        manifest = PhysicalManifest.model_validate(
            {
                "version": "1.0.0",
                "backends": [
                    {
                        "id": "b1",
                        "type": "RDBMS",
                        "provider": "postgresql",
                        "config": {"type": "RDBMS", "uri": "pg://localhost/db"},
                    },
                    {
                        "id": "b2",
                        "type": "VECTOR",
                        "provider": "pinecone",
                        "config": {"type": "VECTOR", "provider": "P", "indexName": "i"},
                    },
                    {
                        "id": "b3",
                        "type": "S3",
                        "provider": "s3",
                        "config": {"type": "S3", "uri": "s3://b/", "region": "us"},
                    },
                    {
                        "id": "b4",
                        "type": "NOSQL",
                        "provider": "mongodb",
                        "config": {"type": "NOSQL", "uri": "mongo://localhost"},
                    },
                    {
                        "id": "b5",
                        "type": "GRAPH",
                        "provider": "neo4j",
                        "config": {"type": "GRAPH", "uri": "neo4j://localhost"},
                    },
                ],
            }
        )
        self.assertEqual(len(manifest.backends), 5)
        types = [b.type for b in manifest.backends]
        self.assertEqual(
            set(types),
            {
                BackendType.RDBMS,
                BackendType.VECTOR,
                BackendType.S3,
                BackendType.NOSQL,
                BackendType.GRAPH,
            },
        )
        providers = [b.provider for b in manifest.backends]
        self.assertEqual(set(providers), {"postgresql", "pinecone", "s3", "mongodb", "neo4j"})
