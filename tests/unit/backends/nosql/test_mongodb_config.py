"""Tests for MongoDB backend configuration handling."""

import unittest

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    NOSQLBackendConfig,
)
from backends.nosql.mongodb import MongoDBBackend

# =============================================================================
# Configuration Tests
# =============================================================================


class TestMongoDBConfiguration(unittest.TestCase):
    def test_config_with_extra_fields(self) -> None:
        """Test that NOSQLBackendConfig accepts extra fields for MongoDB."""
        config = NOSQLBackendConfig.model_validate(
            {"type": "NOSQL", "uri": "mongodb://localhost:27017", "database": "testdb"}
        )

        definition = BackendDefinition(id="test_mongo", type=BackendType.NOSQL, config=config)

        backend = MongoDBBackend(definition=definition)

        # Verify we can access the extra fields
        self.assertEqual(backend._get_database_name(), "testdb")
        self.assertEqual(backend._resolve_uri(), "mongodb://localhost:27017")

    def test_config_with_defaults(self) -> None:
        """Test that MongoDB backend uses defaults when fields are missing."""
        config = NOSQLBackendConfig(type="NOSQL")

        definition = BackendDefinition(id="test_mongo", type=BackendType.NOSQL, config=config)

        backend = MongoDBBackend(definition=definition)

        # Verify defaults are used
        self.assertEqual(backend._get_database_name(), "default")
        self.assertEqual(backend._resolve_uri(), "mongodb://localhost:27017")

    def test_config_from_yaml_style_dict(self) -> None:
        """Test configuration from YAML-style dictionary."""
        config_dict = {
            "type": "NOSQL",
            "uri": "mongodb://mongo.example.com:27017",
            "database": "production",
            "provider": "MONGODB",
        }

        config = NOSQLBackendConfig.model_validate(config_dict)
        definition = BackendDefinition(id="prod_mongo", type=BackendType.NOSQL, config=config)

        backend = MongoDBBackend(definition=definition)

        self.assertEqual(backend._get_database_name(), "production")
        self.assertEqual(backend._resolve_uri(), "mongodb://mongo.example.com:27017")
