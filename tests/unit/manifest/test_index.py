"""Tests for ManifestIndex helper."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import BackendType, PhysicalManifest
from adp_hypervisor.manifest.policy import PolicyManifest
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
                    "config": {"type": "RDBMS", "uri": "postgresql://localhost/db"},
                },
                {
                    "id": "vec1",
                    "type": "VECTOR",
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
                    "sources": [{"source": "events_v1"}],
                },
                {
                    "resourceId": "com.acme:events",
                    "intentClasses": ["QUERY"],
                    "version": 2,
                    "backendId": "db1",
                    "sources": [{"source": "events_v2"}],
                },
            ],
        }
    )

    policy = PolicyManifest.model_validate(
        {
            "version": "1.0.0",
            "policies": [
                {
                    "resourceId": "com.acme:events",
                    "rules": [],
                },
                {
                    "resourceId": "com.acme:*",
                    "rules": [],
                },
            ],
        }
    )

    return physical, semantic, policy


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

    def test_policies_exact_and_wildcard(self) -> None:
        exact = self.index.get_policy("com.acme:events")
        self.assertIsNotNone(exact)
        self.assertEqual(exact.resource_id, "com.acme:events")

        wildcard = self.index.get_policy("com.acme:other")
        self.assertIsNotNone(wildcard)
        self.assertEqual(wildcard.resource_id, "com.acme:*")

        none = self.index.get_policy("com.other:thing")
        self.assertIsNone(none)

        policies = self.index.list_policies()
        self.assertEqual(len(policies), 2)


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
                            "sources": [{"source": "extra"}],
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
