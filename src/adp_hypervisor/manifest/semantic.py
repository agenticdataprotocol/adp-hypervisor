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
        description=(
            "Field definitions for this source. When provided, these define the ADP-visible "
            "field schema for this source. For some backends (for example, opaque blob stores "
            "or key/value stores with arbitrary values), there may be no stable or meaningful "
            "field-level schema; in those cases this property can be omitted and the resource "
            "will be treated as exposing an opaque or implementation-defined payload."
        ),
    )


class CuratedResource(Resource):
    """
    Definition of a resource in the semantic layer.

    Extends Resource with curation-specific fields for backend binding
    and source definitions.
    """

    backend_id: str = PydanticField(
        ...,
        description="Reference to the backend in physical.yaml that provides this resource.",
    )
    sources: list[SourceDefinition] = PydanticField(
        ...,
        description=(
            "List of source definitions for this resource. Currently only a single source "
            "element is supported; the array structure is preserved for future support of "
            "multiple sources per resource. Each source represents a specific data source "
            "within the backend (table, collection, prefix, etc.) and has its own field "
            "definitions. At least one source MUST be provided for each resource."
        ),
    )


class SemanticManifest(ADPModel):
    """Root structure for the semantic manifest (semantic.yaml)."""

    version: str = PydanticField(
        ...,
        description="Version of the manifest schema. Identifies which spec version this manifest follows.",
    )
    resources: list[CuratedResource] = PydanticField(
        ...,
        description=(
            "List of resource definitions. Required. Each entry binds a resourceId to one "
            "backend and (currently) one source. ADP operations like adp.discover and "
            "adp.describe rely on these explicit resource definitions."
        ),
    )
