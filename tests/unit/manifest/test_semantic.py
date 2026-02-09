"""Tests for Semantic Manifest models."""

import unittest

from adp_hypervisor.manifest.semantic import (
    CuratedResource,
    SemanticManifest,
    SourceDefinition,
)
from adp_hypervisor.protocol.types import FieldType, IntentClass

# =============================================================================
# SourceDefinition Tests
# =============================================================================


class TestSourceDefinition(unittest.TestCase):
    def test_minimal_source(self) -> None:
        source = SourceDefinition(source="my_table")
        self.assertEqual(source.source, "my_table")
        self.assertIsNone(source.fields)

    def test_source_with_fields(self) -> None:
        source = SourceDefinition.model_validate(
            {
                "source": "my_table",
                "fields": [
                    {"fieldId": "id", "type": "STRING", "description": "Primary key"},
                    {"fieldId": "name", "type": "STRING"},
                ],
            }
        )
        self.assertEqual(len(source.fields or []), 2)  # type: ignore[arg-type]
        self.assertIsNotNone(source.fields)
        self.assertEqual(source.fields[0].field_id, "id")  # type: ignore[index]
        self.assertEqual(source.fields[0].type, FieldType.STRING)  # type: ignore[index]


# =============================================================================
# CuratedResource Tests
# =============================================================================


class TestCuratedResource(unittest.TestCase):
    def test_full_resource(self) -> None:
        resource = CuratedResource.model_validate(
            {
                "resourceId": "com.acme:bank_failures",
                "intentClasses": ["QUERY"],
                "version": 1,
                "description": "Bank failure records",
                "semanticDescription": "Historical records of bank failures.",
                "tags": ["FINANCE"],
                "backendId": "finance_sql",
                "sources": [
                    {
                        "source": "v_failures_consolidated",
                        "fields": [
                            {"fieldId": "bank_id", "type": "STRING"},
                        ],
                    }
                ],
            }
        )
        self.assertEqual(resource.resource_id, "com.acme:bank_failures")
        self.assertEqual(resource.intent_classes, [IntentClass.QUERY])
        self.assertEqual(resource.version, 1)
        self.assertEqual(resource.backend_id, "finance_sql")
        self.assertIsNotNone(resource.sources)
        self.assertIsNotNone(resource.sources)
        self.assertEqual(len(resource.sources), 1)
        self.assertEqual(resource.sources[0].source, "v_failures_consolidated")

    def test_bootstrap_resource_minimal(self) -> None:
        """Bootstrap mode: only backendId is required."""
        resource = CuratedResource.model_validate({"backendId": "db1"})
        self.assertEqual(resource.backend_id, "db1")
        self.assertIsNone(resource.resource_id)
        self.assertIsNone(resource.sources)
        self.assertIsNone(resource.intent_classes)

    def test_wildcard_intent_class(self) -> None:
        resource = CuratedResource.model_validate(
            {
                "resourceId": "com.acme:universal",
                "intentClasses": ["*"],
                "backendId": "db1",
            }
        )
        self.assertEqual(resource.intent_classes, [IntentClass.WILDCARD])

    def test_inherits_resource_fields(self) -> None:
        """CuratedResource inherits all fields from Resource."""
        resource = CuratedResource.model_validate(
            {
                "resourceId": "com.acme:test",
                "backendId": "db1",
                "tags": ["TAG1", "TAG2"],
                "semanticDescription": "A test resource",
            }
        )
        self.assertEqual(resource.tags, ["TAG1", "TAG2"])
        self.assertEqual(resource.semantic_description, "A test resource")

    def test_serialization_camel_case(self) -> None:
        resource = CuratedResource(backend_id="db1", version=1)
        dumped = resource.model_dump(by_alias=True, exclude_none=True)
        self.assertIn("backendId", dumped)
        self.assertEqual(dumped["backendId"], "db1")


# =============================================================================
# SemanticManifest Tests
# =============================================================================


class TestSemanticManifest(unittest.TestCase):
    def test_full_manifest(self) -> None:
        manifest = SemanticManifest.model_validate(
            {
                "version": "1.0.0",
                "defaultDomain": "com.acme.finance",
                "resources": [
                    {
                        "resourceId": "com.acme.finance:bank_failures",
                        "intentClasses": ["QUERY"],
                        "backendId": "finance_sql",
                        "sources": [
                            {
                                "source": "bank_failures",
                                "fields": [{"fieldId": "id", "type": "STRING"}],
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(manifest.version, "1.0.0")
        self.assertEqual(manifest.default_domain, "com.acme.finance")
        self.assertIsNotNone(manifest.resources)
        self.assertIsNotNone(manifest.resources)
        self.assertEqual(len(manifest.resources), 1)

    def test_bootstrap_manifest_no_resources(self) -> None:
        """Bootstrap mode: no resources array."""
        manifest = SemanticManifest.model_validate(
            {
                "version": "1.0.0",
                "defaultDomain": "com.acme.finance",
            }
        )
        self.assertIsNone(manifest.resources)

    def test_multi_version_resources(self) -> None:
        manifest = SemanticManifest.model_validate(
            {
                "version": "1.0.0",
                "defaultDomain": "com.acme",
                "resources": [
                    {
                        "resourceId": "com.acme:events",
                        "version": 1,
                        "backendId": "db",
                        "sources": [{"source": "events"}],
                    },
                    {
                        "resourceId": "com.acme:events",
                        "version": 2,
                        "backendId": "db",
                        "sources": [{"source": "events"}],
                    },
                ],
            }
        )
        self.assertIsNotNone(manifest.resources)
        self.assertIsNotNone(manifest.resources)
        self.assertEqual(len(manifest.resources), 2)
        self.assertEqual(manifest.resources[0].version, 1)
        self.assertEqual(manifest.resources[1].version, 2)
