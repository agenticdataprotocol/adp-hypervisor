"""Tests for YamlManifestProvider."""

from pathlib import Path

import pytest

from adp_hypervisor.manifest.physical import (
    BackendType,
    RDBMSBackendConfig,
    S3BackendConfig,
    VectorBackendConfig,
)
from adp_hypervisor.manifest.policy import MandatoryFilterRule, OperationalRule
from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def provider() -> YamlManifestProvider:
    p = YamlManifestProvider(
        physical_path=FIXTURES / "physical.yaml",
        semantic_path=FIXTURES / "semantic.yaml",
        policy_path=FIXTURES / "policy.yaml",
    )
    p.load()
    return p


@pytest.fixture()
def bootstrap_provider() -> YamlManifestProvider:
    p = YamlManifestProvider(
        physical_path=FIXTURES / "physical.yaml",
        semantic_path=FIXTURES / "semantic-bootstrap.yaml",
        policy_path=FIXTURES / "policy-bootstrap.yaml",
    )
    p.load()
    return p


# =============================================================================
# Loading Tests
# =============================================================================


class TestYamlManifestProviderLoading:
    def test_load_success(self, provider: YamlManifestProvider) -> None:
        assert provider.get_physical_manifest().version == "1.0.0"
        assert provider.get_semantic_manifest().version == "1.0.0"
        assert provider.get_policy_manifest().version == "1.0.0"

    def test_not_loaded_raises(self) -> None:
        p = YamlManifestProvider(
            physical_path=FIXTURES / "physical.yaml",
            semantic_path=FIXTURES / "semantic.yaml",
            policy_path=FIXTURES / "policy.yaml",
        )
        with pytest.raises(RuntimeError, match="not loaded"):
            p.list_resources()

    def test_invalid_path_raises(self) -> None:
        p = YamlManifestProvider(
            physical_path=FIXTURES / "nonexistent.yaml",
            semantic_path=FIXTURES / "semantic.yaml",
            policy_path=FIXTURES / "policy.yaml",
        )
        with pytest.raises(FileNotFoundError):
            p.load()


# =============================================================================
# Backend Tests
# =============================================================================


class TestYamlManifestProviderBackends:
    def test_list_backends(self, provider: YamlManifestProvider) -> None:
        backends = provider.list_backends()
        assert len(backends) == 5
        ids = {b.id for b in backends}
        expected = {"finance_sql", "report_vectors", "raw_storage", "analytics_nosql", "graph_db"}
        assert ids == expected

    def test_get_backend_rdbms(self, provider: YamlManifestProvider) -> None:
        backend = provider.get_backend("finance_sql")
        assert backend is not None
        assert backend.type == BackendType.RDBMS
        assert isinstance(backend.config, RDBMSBackendConfig)
        assert "5432" in backend.config.uri

    def test_get_backend_vector(self, provider: YamlManifestProvider) -> None:
        backend = provider.get_backend("report_vectors")
        assert backend is not None
        assert backend.type == BackendType.VECTOR
        assert isinstance(backend.config, VectorBackendConfig)
        assert backend.config.index_name == "bank-summaries"

    def test_get_backend_s3(self, provider: YamlManifestProvider) -> None:
        backend = provider.get_backend("raw_storage")
        assert backend is not None
        assert isinstance(backend.config, S3BackendConfig)
        assert backend.config.region == "us-east-1"

    def test_get_backend_not_found(self, provider: YamlManifestProvider) -> None:
        assert provider.get_backend("nonexistent") is None

    def test_credentials(self, provider: YamlManifestProvider) -> None:
        backend = provider.get_backend("finance_sql")
        assert backend is not None
        assert backend.credentials is not None
        assert backend.credentials.type == "env"
        assert backend.credentials.key == "DB_PASSWORD"


# =============================================================================
# Resource Tests
# =============================================================================


class TestYamlManifestProviderResources:
    def test_list_resources(self, provider: YamlManifestProvider) -> None:
        resources = provider.list_resources()
        # bank_failures(1) + audit_events(v1+v2) + universal + failure_vectors = 5
        assert len(resources) == 5

    def test_get_resource_by_id(self, provider: YamlManifestProvider) -> None:
        resource = provider.get_resource("com.acme.finance:bank_failures")
        assert resource is not None
        assert resource.description == "Bank failure records from FDIC"
        assert resource.backend_id == "finance_sql"

    def test_get_resource_not_found(self, provider: YamlManifestProvider) -> None:
        assert provider.get_resource("nonexistent") is None

    def test_get_resource_latest_version(self, provider: YamlManifestProvider) -> None:
        resource = provider.get_resource("com.acme.finance:audit_events")
        assert resource is not None
        assert resource.version == 2

    def test_get_resource_specific_version(self, provider: YamlManifestProvider) -> None:
        v1 = provider.get_resource("com.acme.finance:audit_events", version=1)
        assert v1 is not None
        assert v1.version == 1
        assert v1.description == "Audit events (v1)"

        v2 = provider.get_resource("com.acme.finance:audit_events", version=2)
        assert v2 is not None
        assert v2.version == 2

    def test_get_resource_version_not_found(self, provider: YamlManifestProvider) -> None:
        assert provider.get_resource("com.acme.finance:audit_events", version=99) is None

    def test_resource_sources_and_fields(self, provider: YamlManifestProvider) -> None:
        resource = provider.get_resource("com.acme.finance:bank_failures")
        assert resource is not None
        assert resource.sources is not None
        assert len(resource.sources) == 1
        assert resource.sources[0].source == "v_failures_consolidated"
        assert resource.sources[0].fields is not None
        field_ids = [f.field_id for f in resource.sources[0].fields]
        assert "bank_id" in field_ids
        assert "bank_name" in field_ids
        assert "closing_date" in field_ids

    def test_resource_vector_metadata(self, provider: YamlManifestProvider) -> None:
        resource = provider.get_resource("com.acme.finance:failure_vectors")
        assert resource is not None
        assert resource.sources is not None
        embedding_field = resource.sources[0].fields[0]  # type: ignore[index]
        assert embedding_field.metadata is not None
        assert embedding_field.metadata.vector is not None
        assert embedding_field.metadata.vector["dimensions"] == 1536


# =============================================================================
# Policy Tests
# =============================================================================


class TestYamlManifestProviderPolicies:
    def test_list_policies(self, provider: YamlManifestProvider) -> None:
        policies = provider.list_policies()
        assert len(policies) == 3

    def test_get_policy_exact(self, provider: YamlManifestProvider) -> None:
        policy = provider.get_policy("com.acme.finance:bank_failures")
        assert policy is not None
        assert policy.rules is not None
        assert len(policy.rules) == 2
        assert isinstance(policy.rules[0], MandatoryFilterRule)
        assert isinstance(policy.rules[1], OperationalRule)

    def test_get_policy_wildcard_match(self, provider: YamlManifestProvider) -> None:
        # "com.acme.finance:unknown" should match the wildcard "com.acme.finance:*"
        policy = provider.get_policy("com.acme.finance:unknown")
        assert policy is not None
        assert policy.resource_id == "com.acme.finance:*"

    def test_get_policy_not_found(self, provider: YamlManifestProvider) -> None:
        assert provider.get_policy("com.other:something") is None

    def test_policy_mandatory_filter_details(self, provider: YamlManifestProvider) -> None:
        policy = provider.get_policy("com.acme.finance:bank_failures")
        assert policy is not None
        rule = policy.rules[0]  # type: ignore[index]
        assert isinstance(rule, MandatoryFilterRule)
        assert rule.field_id == "closing_date"
        assert rule.op == "GT"
        assert rule.value == "2020-01-01"
        assert rule.condition == "agent_tier == 'PRODUCTION'"

    def test_policy_operational_details(self, provider: YamlManifestProvider) -> None:
        policy = provider.get_policy("com.acme.finance:bank_failures")
        assert policy is not None
        rule = policy.rules[1]  # type: ignore[index]
        assert isinstance(rule, OperationalRule)
        assert rule.enforce_limit == 100
        assert rule.default_order_by is not None
        assert rule.default_order_by.field_id == "closing_date"
        assert rule.default_order_by.direction == "DESC"


# =============================================================================
# Bootstrap Mode Tests
# =============================================================================


class TestYamlManifestProviderBootstrap:
    def test_bootstrap_semantic_no_resources(
        self, bootstrap_provider: YamlManifestProvider
    ) -> None:
        manifest = bootstrap_provider.get_semantic_manifest()
        assert manifest.default_domain == "com.acme.finance"
        assert manifest.resources is None

    def test_bootstrap_list_resources_empty(self, bootstrap_provider: YamlManifestProvider) -> None:
        assert bootstrap_provider.list_resources() == []

    def test_bootstrap_policy_no_policies(self, bootstrap_provider: YamlManifestProvider) -> None:
        manifest = bootstrap_provider.get_policy_manifest()
        assert manifest.policies is None

    def test_bootstrap_list_policies_empty(self, bootstrap_provider: YamlManifestProvider) -> None:
        assert bootstrap_provider.list_policies() == []

    def test_bootstrap_backends_still_loaded(
        self, bootstrap_provider: YamlManifestProvider
    ) -> None:
        """Physical manifest should still be fully loaded in bootstrap mode."""
        assert len(bootstrap_provider.list_backends()) == 5
