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

"""Tests for MongoDB backend configuration handling."""

import unittest

from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
    NOSQLBackendConfig,
)
from backends.nosql.mongodb import MongoDBBackend, _inject_password

# =============================================================================
# Configuration Tests
# =============================================================================


class TestMongoDBConfiguration(unittest.TestCase):
    def test_config_with_extra_fields(self) -> None:
        """Test that NOSQLBackendConfig accepts extra fields for MongoDB."""
        config = NOSQLBackendConfig.model_validate(
            {"type": "NOSQL", "uri": "mongodb://localhost:27017", "database": "testdb"}
        )

        definition = BackendDefinition(
            id="test_mongo", type=BackendType.NOSQL, provider="mongodb", config=config
        )

        backend = MongoDBBackend(definition=definition)

        # Verify we can access the extra fields
        self.assertEqual(backend._get_database_name(), "testdb")
        self.assertEqual(backend._resolve_uri(), "mongodb://localhost:27017")

    def test_config_with_defaults(self) -> None:
        """Test that MongoDB backend uses defaults when fields are missing."""
        config = NOSQLBackendConfig(type="NOSQL")

        definition = BackendDefinition(
            id="test_mongo", type=BackendType.NOSQL, provider="mongodb", config=config
        )

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
        definition = BackendDefinition(
            id="prod_mongo", type=BackendType.NOSQL, provider="mongodb", config=config
        )

        backend = MongoDBBackend(definition=definition)

        self.assertEqual(backend._get_database_name(), "production")
        self.assertEqual(backend._resolve_uri(), "mongodb://mongo.example.com:27017")


# =============================================================================
# _inject_password Tests
# =============================================================================


class TestInjectPassword(unittest.TestCase):
    def test_inject_into_uri_with_username(self) -> None:
        result = _inject_password("mongodb://user@localhost:27017/db", "secret")
        self.assertEqual(result, "mongodb://user:secret@localhost:27017/db")

    def test_replace_existing_password(self) -> None:
        result = _inject_password("mongodb://user:old@localhost:27017/db", "new")
        self.assertEqual(result, "mongodb://user:new@localhost:27017/db")

    def test_special_chars_in_password_are_encoded(self) -> None:
        result = _inject_password("mongodb://user@localhost:27017/db", "p@ss:w0rd/foo")
        self.assertIn("p%40ss%3Aw0rd%2Ffoo", result)

    def test_no_username_returns_uri_unchanged(self) -> None:
        uri = "mongodb://localhost:27017/db"
        result = _inject_password(uri, "secret")
        self.assertEqual(result, uri)

    def test_replica_set_uri_preserves_all_hosts(self) -> None:
        uri = "mongodb://user@host1:27017,host2:27017,host3:27017/db?replicaSet=rs0"
        result = _inject_password(uri, "secret")
        self.assertIn("host1:27017,host2:27017,host3:27017", result)
        self.assertIn("user:secret@", result)

    def test_invalid_uri_returns_unchanged(self) -> None:
        uri = "not-a-url"
        result = _inject_password(uri, "secret")
        self.assertEqual(result, uri)
