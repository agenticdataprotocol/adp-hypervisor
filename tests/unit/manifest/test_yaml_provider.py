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

"""Tests for YamlManifestProvider."""

import unittest
from pathlib import Path

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import (
    BackendType,
    BlobStorageBackendConfig,
    RDBMSBackendConfig,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.policy import (
    AccessPolicy,
    MandatoryFilterPolicy,
    OperationalPolicy,
)
from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _make_provider() -> YamlManifestProvider:
    p = YamlManifestProvider(
        physical_path=FIXTURES / "physical.yaml",
        semantic_path=FIXTURES / "semantic.yaml",
        policy_path=FIXTURES / "policy.yaml",
    )
    p.load()
    return p


def _make_bootstrap_provider() -> YamlManifestProvider:
    p = YamlManifestProvider(
        physical_path=FIXTURES / "physical.yaml",
        semantic_path=FIXTURES / "semantic.yaml",
        policy_path=FIXTURES / "policy-bootstrap.yaml",
    )
    p.load()
    return p


def _make_index() -> ManifestIndex:
    """Helper that returns a ManifestIndex built on a loaded YAML provider."""
    provider = _make_provider()
    return ManifestIndex(provider)


def _make_bootstrap_index() -> ManifestIndex:
    provider = _make_bootstrap_provider()
    return ManifestIndex(provider)


# =============================================================================
# Loading Tests
# =============================================================================


class TestYamlManifestProviderLoading(unittest.TestCase):
    def test_load_success(self) -> None:
        provider = _make_provider()
        self.assertEqual(provider.get_physical_manifest().version, "1.0.0")
        self.assertEqual(provider.get_semantic_manifest().version, "1.0.0")
        self.assertEqual(provider.get_policy_manifest().version, "1.0.0")

    def test_not_loaded_raises(self) -> None:
        p = YamlManifestProvider(
            physical_path=FIXTURES / "physical.yaml",
            semantic_path=FIXTURES / "semantic.yaml",
            policy_path=FIXTURES / "policy.yaml",
        )
        index = ManifestIndex(p)
        with self.assertRaisesRegex(RuntimeError, "not loaded"):
            index.list_resources()

    def test_invalid_path_raises(self) -> None:
        p = YamlManifestProvider(
            physical_path=FIXTURES / "nonexistent.yaml",
            semantic_path=FIXTURES / "semantic.yaml",
            policy_path=FIXTURES / "policy.yaml",
        )
        with self.assertRaises(FileNotFoundError):
            p.load()


# =============================================================================
# Backend Tests
# =============================================================================


class TestYamlManifestProviderBackends(unittest.TestCase):
    def test_list_backends(self) -> None:
        index = _make_index()
        backends = index.list_backends()
        self.assertEqual(len(backends), 5)
        ids = {b.id for b in backends}
        expected = {"finance_sql", "report_vectors", "raw_storage", "analytics_nosql", "graph_db"}
        self.assertEqual(ids, expected)

    def test_get_backend_rdbms(self) -> None:
        index = _make_index()
        backend = index.get_backend("finance_sql")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.type, BackendType.RDBMS)
        self.assertIsInstance(backend.config, RDBMSBackendConfig)
        self.assertIn("5432", backend.config.uri)

    def test_get_backend_vector(self) -> None:
        index = _make_index()
        backend = index.get_backend("report_vectors")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.type, BackendType.VECTOR)
        self.assertIsInstance(backend.config, VectorBackendConfig)
        self.assertEqual(backend.config.index_name, "bank-summaries")

    def test_get_backend_blob_storage(self) -> None:
        index = _make_index()
        backend = index.get_backend("raw_storage")
        self.assertIsNotNone(backend)
        self.assertIsInstance(backend.config, BlobStorageBackendConfig)
        self.assertEqual(backend.config.uri, "s3://acme-finance-datalake/")

    def test_get_backend_not_found(self) -> None:
        index = _make_index()
        self.assertIsNone(index.get_backend("nonexistent"))

    def test_credentials(self) -> None:
        index = _make_index()
        backend = index.get_backend("finance_sql")
        self.assertIsNotNone(backend)
        self.assertIsNotNone(backend.credentials)
        self.assertEqual(backend.credentials.type, "env")
        self.assertEqual(backend.credentials.key, "DB_PASSWORD")


# =============================================================================
# Resource Tests
# =============================================================================


class TestYamlManifestProviderResources(unittest.TestCase):
    def test_list_resources(self) -> None:
        index = _make_index()
        resources = index.list_resources()
        # bank_failures(1) + audit_events(v1+v2) + universal + failure_vectors = 5
        self.assertEqual(len(resources), 5)

    def test_get_resource_by_id(self) -> None:
        index = _make_index()
        resource = index.get_resource("com.acme.finance:bank_failures")
        self.assertIsNotNone(resource)
        self.assertEqual(resource.description, "Bank failure records from FDIC")
        self.assertEqual(resource.backend_id, "finance_sql")

    def test_get_resource_not_found(self) -> None:
        index = _make_index()
        self.assertIsNone(index.get_resource("nonexistent"))

    def test_get_resource_latest_version(self) -> None:
        index = _make_index()
        resource = index.get_resource("com.acme.finance:audit_events")
        self.assertIsNotNone(resource)
        self.assertEqual(resource.version, 2)

    def test_get_resource_specific_version(self) -> None:
        index = _make_index()
        v1 = index.get_resource("com.acme.finance:audit_events", version=1)
        self.assertIsNotNone(v1)
        self.assertEqual(v1.version, 1)
        self.assertEqual(v1.description, "Audit events (v1 - core fields only)")

        v2 = index.get_resource("com.acme.finance:audit_events", version=2)
        self.assertIsNotNone(v2)
        self.assertEqual(v2.version, 2)

    def test_get_resource_version_not_found(self) -> None:
        index = _make_index()
        self.assertIsNone(index.get_resource("com.acme.finance:audit_events", version=99))

    def test_resource_sources_and_fields(self) -> None:
        index = _make_index()
        resource = index.get_resource("com.acme.finance:bank_failures")
        self.assertIsNotNone(resource)
        self.assertIsNotNone(resource.source_definition)
        self.assertEqual(resource.source_definition.source, "v_failures_consolidated")
        self.assertIsNotNone(resource.source_definition.fields)
        field_ids = [f.field_id for f in resource.source_definition.fields]
        self.assertIn("bank_id", field_ids)
        self.assertIn("bank_name", field_ids)
        self.assertIn("closing_date", field_ids)

    def test_resource_vector_metadata(self) -> None:
        index = _make_index()
        resource = index.get_resource("com.acme.finance:failure_vectors")
        self.assertIsNotNone(resource)
        self.assertIsNotNone(resource.source_definition)
        embedding_field = resource.source_definition.fields[0]  # type: ignore[index]
        self.assertIsNotNone(embedding_field.metadata)
        self.assertIsNotNone(embedding_field.metadata.vector)
        self.assertEqual(embedding_field.metadata.vector["dimensions"], 1536)


# =============================================================================
# Policy Tests
# =============================================================================


class TestYamlManifestProviderPolicies(unittest.TestCase):
    def test_list_policies(self) -> None:
        index = _make_index()
        policies = index.list_policies()
        self.assertEqual(len(policies), 4)

    def test_get_access_policy_exact(self) -> None:
        index = _make_index()
        policy = index.get_access_policy("com.acme.finance:bank_failures")
        self.assertIsNotNone(policy)
        self.assertIsInstance(policy, AccessPolicy)
        self.assertEqual(policy.resource_selector, "com.acme.finance:bank_failures")
        self.assertEqual(len(policy.roles), 2)
        roles = {r.role for r in policy.roles}
        self.assertIn("admin", roles)
        self.assertIn("user", roles)

    def test_get_access_policy_wildcard_match(self) -> None:
        index = _make_index()
        # "com.acme.finance:unknown" should match the wildcard "com.acme.finance:*"
        policy = index.get_access_policy("com.acme.finance:unknown")
        self.assertIsNotNone(policy)
        self.assertIsInstance(policy, AccessPolicy)
        self.assertEqual(policy.resource_selector, "com.acme.finance:*")

    def test_get_access_policy_not_found(self) -> None:
        index = _make_index()
        self.assertIsNone(index.get_access_policy("com.other:something"))

    def test_mandatory_filter_details(self) -> None:
        index = _make_index()
        policies = index.get_mandatory_filter_policies("com.acme.finance:bank_failures")
        self.assertEqual(len(policies), 1)
        policy = policies[0]
        self.assertIsInstance(policy, MandatoryFilterPolicy)
        self.assertEqual(policy.field_id, "closing_date")
        self.assertEqual(policy.op, "GT")
        self.assertEqual(policy.value, "2020-01-01")
        self.assertEqual(policy.condition, "agent_tier == 'PRODUCTION'")

    def test_operational_details(self) -> None:
        index = _make_index()
        policy = index.get_operational_policy("com.acme.finance:bank_failures")
        self.assertIsNotNone(policy)
        self.assertIsInstance(policy, OperationalPolicy)
        self.assertEqual(policy.enforce_limit, 100)
        self.assertIsNotNone(policy.default_order_by)
        self.assertEqual(policy.default_order_by.field_id, "closing_date")
        self.assertEqual(policy.default_order_by.direction, "DESC")


# =============================================================================
# Bootstrap Mode Tests
# =============================================================================


class TestYamlManifestProviderBootstrap(unittest.TestCase):
    def test_bootstrap_policy_has_catchall_access(self) -> None:
        bootstrap_provider = _make_bootstrap_provider()
        manifest = bootstrap_provider.get_policy_manifest()
        self.assertIsNotNone(manifest.policies)
        self.assertEqual(len(manifest.policies), 1)  # type: ignore[arg-type]
        policy = manifest.policies[0]  # type: ignore[index]
        self.assertIsInstance(policy, AccessPolicy)
        self.assertEqual(policy.resource_selector, "*")

    def test_bootstrap_list_policies_has_one_entry(self) -> None:
        index = _make_bootstrap_index()
        self.assertEqual(len(index.list_policies()), 1)

    def test_bootstrap_backends_still_loaded(self) -> None:
        index = _make_bootstrap_index()
        """Physical manifest should still be fully loaded in bootstrap mode."""
        self.assertEqual(len(index.list_backends()), 5)
