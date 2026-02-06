"""
Semantic Manifest models.

Defines the types for the ADP Curation Plane's semantic layer,
which maps physical data sources to ADP resources and defines
the "Agent's View" of fields.
Based on the SemanticManifest section of curation.ts.
"""

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import ADPModel, Field, Resource


class SourceDefinition(ADPModel):
    """
    Definition of a source within a resource.

    Each source represents a specific data source (table, collection, prefix, etc.)
    within a backend, with its own field definitions.
    """

    source: str = PydanticField(
        ...,
        description="Source identifier in the backend (table name, collection, prefix, etc.)",
    )
    fields: list[Field] | None = PydanticField(
        default=None,
        description="Field definitions for this source. If omitted, fields will be auto-discovered",
    )


class CuratedResource(Resource):
    """
    Definition of a resource in the semantic layer.

    Extends Resource with curation-specific fields for backend binding
    and source definitions.
    """

    backend_id: str = PydanticField(..., description="Reference to the backend in physical.yaml")
    sources: list[SourceDefinition] | None = PydanticField(
        default=None,
        description="List of source definitions. Currently only single source is supported",
    )


class SemanticManifest(ADPModel):
    """Root structure for the semantic manifest (semantic.yaml)."""

    version: str = PydanticField(..., description="Version of the manifest schema")
    default_domain: str = PydanticField(
        ..., description="Default domain prefix for auto-generating resourceIds"
    )
    resources: list[CuratedResource] | None = PydanticField(
        default=None,
        description="List of resource definitions. If omitted, resources will be auto-discovered",
    )
