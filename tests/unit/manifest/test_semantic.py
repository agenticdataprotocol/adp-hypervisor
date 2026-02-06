"""Tests for Semantic Manifest models."""

from adp_hypervisor.manifest.semantic import (
    CuratedResource,
    SemanticManifest,
    SourceDefinition,
)
from adp_hypervisor.protocol.types import FieldType, IntentClass

# =============================================================================
# SourceDefinition Tests
# =============================================================================


class TestSourceDefinition:
    def test_minimal_source(self) -> None:
        source = SourceDefinition(source="my_table")
        assert source.source == "my_table"
        assert source.fields is None

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
        assert len(source.fields) == 2  # type: ignore[arg-type]
        assert source.fields[0].field_id == "id"  # type: ignore[index]
        assert source.fields[0].type == FieldType.STRING  # type: ignore[index]


# =============================================================================
# CuratedResource Tests
# =============================================================================


class TestCuratedResource:
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
        assert resource.resource_id == "com.acme:bank_failures"
        assert resource.intent_classes == [IntentClass.QUERY]
        assert resource.version == 1
        assert resource.backend_id == "finance_sql"
        assert resource.sources is not None
        assert len(resource.sources) == 1
        assert resource.sources[0].source == "v_failures_consolidated"

    def test_bootstrap_resource_minimal(self) -> None:
        """Bootstrap mode: only backendId is required."""
        resource = CuratedResource.model_validate({"backendId": "db1"})
        assert resource.backend_id == "db1"
        assert resource.resource_id is None
        assert resource.sources is None
        assert resource.intent_classes is None

    def test_wildcard_intent_class(self) -> None:
        resource = CuratedResource.model_validate(
            {
                "resourceId": "com.acme:universal",
                "intentClasses": ["*"],
                "backendId": "db1",
            }
        )
        assert resource.intent_classes == [IntentClass.WILDCARD]

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
        assert resource.tags == ["TAG1", "TAG2"]
        assert resource.semantic_description == "A test resource"

    def test_serialization_camel_case(self) -> None:
        resource = CuratedResource(backend_id="db1", version=1)
        dumped = resource.model_dump(by_alias=True, exclude_none=True)
        assert "backendId" in dumped
        assert dumped["backendId"] == "db1"


# =============================================================================
# SemanticManifest Tests
# =============================================================================


class TestSemanticManifest:
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
        assert manifest.version == "1.0.0"
        assert manifest.default_domain == "com.acme.finance"
        assert manifest.resources is not None
        assert len(manifest.resources) == 1

    def test_bootstrap_manifest_no_resources(self) -> None:
        """Bootstrap mode: no resources array."""
        manifest = SemanticManifest.model_validate(
            {
                "version": "1.0.0",
                "defaultDomain": "com.acme.finance",
            }
        )
        assert manifest.resources is None

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
        assert manifest.resources is not None
        assert len(manifest.resources) == 2
        assert manifest.resources[0].version == 1
        assert manifest.resources[1].version == 2
