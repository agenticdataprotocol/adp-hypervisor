"""Tests for YamlManifestProvider."""

import unittest
from pathlib import Path

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import (
    BackendType,
    RDBMSBackendConfig,
    S3BackendConfig,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.policy import MandatoryFilterRule, OperationalRule
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
        semantic_path=FIXTURES / "semantic-bootstrap.yaml",
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

    def test_get_backend_s3(self) -> None:
        index = _make_index()
        backend = index.get_backend("raw_storage")
        self.assertIsNotNone(backend)
        self.assertIsInstance(backend.config, S3BackendConfig)
        self.assertEqual(backend.config.region, "us-east-1")

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
        self.assertEqual(v1.description, "Audit events (v1)")

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
        self.assertIsNotNone(resource.sources)
        self.assertEqual(len(resource.sources), 1)
        self.assertEqual(resource.sources[0].source, "v_failures_consolidated")
        self.assertIsNotNone(resource.sources[0].fields)
        field_ids = [f.field_id for f in resource.sources[0].fields]
        self.assertIn("bank_id", field_ids)
        self.assertIn("bank_name", field_ids)
        self.assertIn("closing_date", field_ids)

    def test_resource_vector_metadata(self) -> None:
        index = _make_index()
        resource = index.get_resource("com.acme.finance:failure_vectors")
        self.assertIsNotNone(resource)
        self.assertIsNotNone(resource.sources)
        embedding_field = resource.sources[0].fields[0]  # type: ignore[index]
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
        self.assertEqual(len(policies), 3)

    def test_get_policy_exact(self) -> None:
        index = _make_index()
        policy = index.get_policy("com.acme.finance:bank_failures")
        self.assertIsNotNone(policy)
        self.assertIsNotNone(policy.rules)
        self.assertEqual(len(policy.rules), 2)
        self.assertIsInstance(policy.rules[0], MandatoryFilterRule)
        self.assertIsInstance(policy.rules[1], OperationalRule)

    def test_get_policy_wildcard_match(self) -> None:
        index = _make_index()
        # "com.acme.finance:unknown" should match the wildcard "com.acme.finance:*"
        policy = index.get_policy("com.acme.finance:unknown")
        self.assertIsNotNone(policy)
        self.assertEqual(policy.resource_id, "com.acme.finance:*")

    def test_get_policy_not_found(self) -> None:
        index = _make_index()
        self.assertIsNone(index.get_policy("com.other:something"))

    def test_policy_mandatory_filter_details(self) -> None:
        index = _make_index()
        policy = index.get_policy("com.acme.finance:bank_failures")
        self.assertIsNotNone(policy)
        rule = policy.rules[0]  # type: ignore[index]
        self.assertIsInstance(rule, MandatoryFilterRule)
        self.assertEqual(rule.field_id, "closing_date")
        self.assertEqual(rule.op, "GT")
        self.assertEqual(rule.value, "2020-01-01")
        self.assertEqual(rule.condition, "agent_tier == 'PRODUCTION'")

    def test_policy_operational_details(self) -> None:
        index = _make_index()
        policy = index.get_policy("com.acme.finance:bank_failures")
        self.assertIsNotNone(policy)
        rule = policy.rules[1]  # type: ignore[index]
        self.assertIsInstance(rule, OperationalRule)
        self.assertEqual(rule.enforce_limit, 100)
        self.assertIsNotNone(rule.default_order_by)
        self.assertEqual(rule.default_order_by.field_id, "closing_date")
        self.assertEqual(rule.default_order_by.direction, "DESC")


# =============================================================================
# Bootstrap Mode Tests
# =============================================================================


class TestYamlManifestProviderBootstrap(unittest.TestCase):
    def test_bootstrap_semantic_no_resources(self) -> None:
        bootstrap_provider = _make_bootstrap_provider()
        manifest = bootstrap_provider.get_semantic_manifest()
        self.assertEqual(manifest.default_domain, "com.acme.finance")
        self.assertIsNone(manifest.resources)

    def test_bootstrap_list_resources_empty(self) -> None:
        index = _make_bootstrap_index()
        self.assertEqual(index.list_resources(), [])

    def test_bootstrap_policy_no_policies(self) -> None:
        bootstrap_provider = _make_bootstrap_provider()
        manifest = bootstrap_provider.get_policy_manifest()
        self.assertIsNone(manifest.policies)

    def test_bootstrap_list_policies_empty(self) -> None:
        index = _make_bootstrap_index()
        self.assertEqual(index.list_policies(), [])

    def test_bootstrap_backends_still_loaded(self) -> None:
        index = _make_bootstrap_index()
        """Physical manifest should still be fully loaded in bootstrap mode."""
        self.assertEqual(len(index.list_backends()), 5)
