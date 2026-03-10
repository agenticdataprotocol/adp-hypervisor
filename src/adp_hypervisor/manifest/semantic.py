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
    and a single source definition.
    """

    backend_id: str = PydanticField(
        ...,
        description="Reference to the backend in physical.yaml that provides this resource.",
    )
    source_definition: SourceDefinition = PydanticField(
        ...,
        description=(
            "Source definition for this resource. Represents the single data source within "
            "the backend (table, collection, prefix, etc.) that backs this resource and "
            "defines its fields."
        ),
    )


class SemanticManifest(ADPModel):
    """Root structure for the semantic manifest (semantic.yaml)."""

    version: str = PydanticField(
        ...,
        description=(
            "Version of the manifest schema. Identifies which spec version this "
            "manifest follows."
        ),
    )
    resources: list[CuratedResource] = PydanticField(
        ...,
        description=(
            "List of resource definitions. Required. Each entry binds a resourceId to one "
            "backend and one source definition. ADP operations like adp.discover and "
            "adp.describe rely on these explicit resource definitions."
        ),
    )
