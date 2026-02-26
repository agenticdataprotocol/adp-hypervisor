"""Tests for ManifestIndex helper."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from adp_hypervisor.manifest.index import (
    ManifestIndex,
    _is_valid_concrete_resource_id,
    _is_valid_resource_selector,
)
from adp_hypervisor.manifest.physical import BackendType, PhysicalManifest
from adp_hypervisor.manifest.policy import (
    AccessPolicy,
    MandatoryFilterPolicy,
    OperationalPolicy,
    PolicyManifest,
)
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.manifest.semantic import CuratedResource, SemanticManifest


class _FakeProvider(ManifestProvider):
    """Simple in-memory ManifestProvider for testing ManifestIndex."""

    def __init__(
        self,
        physical: PhysicalManifest | None = None,
        semantic: SemanticManifest | None = None,
        policy: PolicyManifest | None = None,
    ) -> None:
        self._physical = physical
        self._semantic = semantic
        self._policy = policy

    def load(self) -> None:  # pragma: no cover - trivial for this fake
        # In tests we set manifests directly; nothing to do here.
        if self._physical is None or self._semantic is None or self._policy is None:
            raise RuntimeError("FakeProvider not initialized with manifests")

    def get_physical_manifest(self) -> PhysicalManifest:
        if self._physical is None:
            raise RuntimeError("Physical manifest not loaded")
        return self._physical

    def get_semantic_manifest(self) -> SemanticManifest:
        if self._semantic is None:
            raise RuntimeError("Semantic manifest not loaded")
        return self._semantic

    def get_policy_manifest(self) -> PolicyManifest:
        if self._policy is None:
            raise RuntimeError("Policy manifest not loaded")
        return self._policy


def _make_sample_manifests() -> tuple[PhysicalManifest, SemanticManifest, PolicyManifest]:
    physical = PhysicalManifest.model_validate(
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
                    "config": {"type": "VECTOR", "provider": "P", "indexName": "idx"},
                },
            ],
        }
    )

    semantic = SemanticManifest.model_validate(
        {
            "version": "1.0.0",
            "resources": [
                {
                    "resourceId": "com.acme:events",
                    "intentClasses": ["QUERY"],
                    "version": 1,
                    "backendId": "db1",
                    "sourceDefinition": {"source": "events_v1"},
                },
                {
                    "resourceId": "com.acme:events",
                    "intentClasses": ["QUERY"],
                    "version": 2,
                    "backendId": "db1",
                    "sourceDefinition": {"source": "events_v2"},
                },
            ],
        }
    )

    policy = PolicyManifest.model_validate(
        {
            "version": "1.0.0",
            "policies": [
                {
                    "type": "ACCESS",
                    "resourceSelector": "com.acme:events",
                    "roles": [{"role": "admin", "allowedIntents": ["LOOKUP", "QUERY"]}],
                },
                {
                    "type": "MANDATORY_FILTER",
                    "resourceId": "com.acme:events",
                    "fieldId": "created_at",
                    "op": "GT",
                    "value": "2020-01-01",
                },
                {
                    "type": "OPERATIONAL",
                    "resourceId": "com.acme:events",
                    "enforceLimit": 100,
                },
                {
                    "type": "ACCESS",
                    "resourceSelector": "com.acme:*",
                    "roles": [{"role": "viewer", "allowedIntents": ["LOOKUP", "QUERY"]}],
                },
            ],
        }
    )

    return physical, semantic, policy


# =============================================================================
# TestManifestIndexBasics
# =============================================================================


class TestManifestIndexBasics(unittest.TestCase):
    def setUp(self) -> None:
        physical, semantic, policy = _make_sample_manifests()
        self.provider = _FakeProvider(physical=physical, semantic=semantic, policy=policy)
        self.index = ManifestIndex(self.provider)

    def test_backends_indexed(self) -> None:
        backends = self.index.list_backends()
        self.assertEqual(len(backends), 2)
        ids = {b.id for b in backends}
        self.assertEqual(ids, {"db1", "vec1"})

        backend = self.index.get_backend("db1")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.type, BackendType.RDBMS)
        self.assertEqual(backend.provider, "postgresql")

    def test_resources_latest_and_specific_versions(self) -> None:
        # Latest version
        latest = self.index.get_resource("com.acme:events")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.version, 2)

        # Specific versions
        v1 = self.index.get_resource("com.acme:events", version=1)
        self.assertIsNotNone(v1)
        self.assertEqual(v1.version, 1)

        missing = self.index.get_resource("com.acme:events", version=99)
        self.assertIsNone(missing)

        # list_resources returns both versions
        resources = self.index.list_resources()
        self.assertEqual(len(resources), 2)
        versions = sorted(r.version for r in resources if r.version is not None)
        self.assertEqual(versions, [1, 2])

    def test_policies_typed_lookups(self) -> None:
        # ACCESS: exact match beats wildcard
        exact_ap = self.index.get_access_policy("com.acme:events")
        self.assertIsNotNone(exact_ap)
        self.assertIsInstance(exact_ap, AccessPolicy)
        self.assertEqual(exact_ap.resource_selector, "com.acme:events")

        # ACCESS: wildcard fallback for unmatched exact
        wildcard_ap = self.index.get_access_policy("com.acme:other")
        self.assertIsNotNone(wildcard_ap)
        self.assertEqual(wildcard_ap.resource_selector, "com.acme:*")

        # ACCESS: no match for a different namespace
        no_match = self.index.get_access_policy("com.other:thing")
        self.assertIsNone(no_match)

        # MANDATORY_FILTER
        mf_policies = self.index.get_mandatory_filter_policies("com.acme:events")
        self.assertEqual(len(mf_policies), 1)
        self.assertIsInstance(mf_policies[0], MandatoryFilterPolicy)
        self.assertEqual(mf_policies[0].field_id, "created_at")

        # MANDATORY_FILTER: no match
        self.assertEqual(self.index.get_mandatory_filter_policies("com.acme:other"), [])

        # OPERATIONAL
        op = self.index.get_operational_policy("com.acme:events")
        self.assertIsNotNone(op)
        self.assertIsInstance(op, OperationalPolicy)
        self.assertEqual(op.enforce_limit, 100)

        # OPERATIONAL: no match
        self.assertIsNone(self.index.get_operational_policy("com.acme:other"))

        # list_policies returns all 4
        policies = self.index.list_policies()
        self.assertEqual(len(policies), 4)


# =============================================================================
# TestManifestIndexRefresh
# =============================================================================


class TestManifestIndexRefresh(unittest.TestCase):
    def test_refresh_rebuilds_indexes_after_provider_change(self) -> None:
        physical, semantic, policy = _make_sample_manifests()
        provider = _FakeProvider(physical=physical, semantic=semantic, policy=policy)
        index = ManifestIndex(provider)

        # Initial state: two backends
        self.assertEqual(len(index.list_backends()), 2)

        # Modify provider manifests: add a new backend and resource
        physical2 = PhysicalManifest.model_validate(
            {
                "version": "1.0.1",
                "backends": [
                    *[b.model_dump(by_alias=True) for b in physical.backends],
                    {
                        "id": "db2",
                        "type": "RDBMS",
                        "provider": "postgresql",
                        "config": {"type": "RDBMS", "uri": "postgresql://localhost/db2"},
                    },
                ],
            }
        )
        semantic2 = semantic.model_copy(
            update={
                "resources": [
                    *semantic.resources,
                    CuratedResource.model_validate(
                        {
                            "resourceId": "com.acme:extra",
                            "intentClasses": ["QUERY"],
                            "backendId": "db2",
                            "version": 1,
                            "sourceDefinition": {"source": "extra"},
                        }
                    ),
                ]
            }
        )

        provider._physical = physical2
        provider._semantic = semantic2

        # Without refresh(), index still sees old state
        self.assertEqual(len(index.list_backends()), 2)

        # After refresh, new backend and resource are visible
        index.refresh()
        self.assertEqual(len(index.list_backends()), 3)
        self.assertIsNotNone(index.get_backend("db2"))
        self.assertIsNotNone(index.get_resource("com.acme:extra"))


# =============================================================================
# TestManifestIndexThreadSafety
# =============================================================================


class TestManifestIndexThreadSafety(unittest.TestCase):
    def test_concurrent_access_is_safe(self) -> None:
        physical, semantic, policy = _make_sample_manifests()
        provider = _FakeProvider(physical=physical, semantic=semantic, policy=policy)
        index = ManifestIndex(provider)

        results_lock = threading.Lock()
        seen_lengths: list[int] = []

        def worker() -> None:
            # Interleave different operations
            backends = index.list_backends()
            resources = index.list_resources()
            policies = index.list_policies()
            with results_lock:
                seen_lengths.append(len(backends) + len(resources) + len(policies))

        with ThreadPoolExecutor(max_workers=8) as executor:
            for _ in range(32):
                executor.submit(worker)

        # All threads should have completed without raising, and all should see
        # the same total object count.
        self.assertEqual(len(seen_lengths), 32)
        self.assertEqual(len(set(seen_lengths)), 1)


# =============================================================================
# TestManifestIndexResourceSelectorDefensive
# =============================================================================


class TestResourceSelectorValidation(unittest.TestCase):
    """Test ResourceSelector validation (spec: * only as final token)."""

    def test_valid_selectors(self) -> None:
        self.assertTrue(_is_valid_resource_selector("*"))
        self.assertTrue(_is_valid_resource_selector("com.acme:events"))
        self.assertTrue(_is_valid_resource_selector("com.acme:*"))
        self.assertTrue(_is_valid_resource_selector("com.acme.*"))
        self.assertTrue(_is_valid_resource_selector("com.acme.finance.*"))
        self.assertTrue(_is_valid_resource_selector("  com.acme:name  "))

    def test_invalid_selectors(self) -> None:
        self.assertFalse(_is_valid_resource_selector(""))
        self.assertFalse(_is_valid_resource_selector("   "))
        self.assertFalse(_is_valid_resource_selector("a*"))
        self.assertFalse(_is_valid_resource_selector("com.acme.*:name"))
        self.assertFalse(_is_valid_resource_selector("com.acme.*:*"))
        self.assertFalse(_is_valid_resource_selector("no-colon"))
        self.assertFalse(_is_valid_resource_selector("ns:*:extra"))
        self.assertFalse(_is_valid_resource_selector("ns:"))
        self.assertFalse(_is_valid_resource_selector(":name"))


class TestConcreteResourceIdValidation(unittest.TestCase):
    """Test concrete ResourceId validation for matching."""

    def test_valid_concrete_ids(self) -> None:
        self.assertTrue(_is_valid_concrete_resource_id("com.acme:events"))
        self.assertTrue(_is_valid_concrete_resource_id("a:b"))

    def test_invalid_concrete_ids(self) -> None:
        self.assertFalse(_is_valid_concrete_resource_id(""))
        self.assertFalse(_is_valid_concrete_resource_id("   "))
        self.assertFalse(_is_valid_concrete_resource_id("no-colon"))
        self.assertFalse(_is_valid_concrete_resource_id("com.acme:*"))
        self.assertFalse(_is_valid_concrete_resource_id("ns:"))
        self.assertFalse(_is_valid_concrete_resource_id(":name"))
        self.assertFalse(_is_valid_concrete_resource_id("a:b:c"))


class TestManifestIndexResourceSelectorDefensive(unittest.TestCase):
    """Test defensive behavior: invalid selectors skipped, invalid resource_id does not match."""

    def test_invalid_resource_id_returns_none(self) -> None:
        physical, semantic, policy = _make_sample_manifests()
        provider = _FakeProvider(physical=physical, semantic=semantic, policy=policy)
        index = ManifestIndex(provider)
        self.assertIsNone(index.get_access_policy(""))
        self.assertIsNone(index.get_access_policy("no-colon"))
        self.assertIsNone(index.get_access_policy("com.acme:*"))

    def test_invalid_access_selector_skipped(self) -> None:
        """ACCESS policies with invalid resourceSelector are skipped at index build."""
        physical, semantic, _ = _make_sample_manifests()
        policy_with_bad = PolicyManifest.model_validate(
            {
                "version": "1.0.0",
                "policies": [
                    {"type": "ACCESS", "resourceSelector": "com.acme:events", "roles": []},
                    {"type": "ACCESS", "resourceSelector": "bad*", "roles": []},
                    {"type": "ACCESS", "resourceSelector": "com.acme.*:name", "roles": []},
                ],
            }
        )
        provider = _FakeProvider(physical=physical, semantic=semantic, policy=policy_with_bad)
        index = ManifestIndex(provider)
        policies = index.list_policies()
        access_only = [p for p in policies if isinstance(p, AccessPolicy)]
        self.assertEqual(len(access_only), 1)
        self.assertEqual(access_only[0].resource_selector, "com.acme:events")
        self.assertIsNotNone(index.get_access_policy("com.acme:events"))
