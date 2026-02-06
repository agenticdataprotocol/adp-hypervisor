"""
ADP Protocol Type Definitions.

This module defines Pydantic models for the Agentic Data Protocol (ADP),
based on the JSON-RPC 2.0 protocol specification.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField
from pydantic.alias_generators import to_camel

from adp_hypervisor.protocol.jsonrpc import (
    JSONRPC_VERSION,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCResultResponse,
    RequestId,
    RequestParams,
    Result,
)

__all__ = [
    # Re-exported from jsonrpc
    "JSONRPC_VERSION",
    "JSONRPCError",
    "JSONRPCErrorResponse",
    "JSONRPCMessage",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCResultResponse",
    "RequestId",
    "RequestParams",
    "Result",
]


# =============================================================================
# Constants
# =============================================================================

LATEST_PROTOCOL_VERSION = "2026-01-20"


# =============================================================================
# Base Models
# =============================================================================


class ADPModel(BaseModel):
    """
    Base model for all ADP types.

    Configured to automatically generate camelCase aliases for fields,
    allowing for standard Python snake_case usage within the codebase
    while ensuring protocol compliance (camelCase) for serialization.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# =============================================================================
# Common Type Aliases
# =============================================================================

ProgressToken = str | int
"""A progress token, used to associate progress notifications with the original request."""

Cursor = str
"""An opaque token used to represent a cursor for pagination."""

ResourceId = str
"""A domain-qualified entity identifier using the format `domain:alias`."""

TraceId = str
"""A unique identifier for tracing and debugging purposes."""


# =============================================================================
# Enums
# =============================================================================


class IntentClass(StrEnum):
    """
    Intent classes for data operations.

    READ operations:
    - LOOKUP: Retrieve a single entity by unique key
    - QUERY: Retrieve a set of entities using boolean predicates

    WRITE operations:
    - INGEST: Create or append new data entries
    - REVISE: Update existing entries (full or partial)

    WILDCARD: Accepts any intent class
    """

    LOOKUP = "LOOKUP"
    QUERY = "QUERY"
    INGEST = "INGEST"
    REVISE = "REVISE"
    WILDCARD = "*"


class PredicateOperator(StrEnum):
    """Operators supported for predicate expressions."""

    EQ = "EQ"  # Equal
    NEQ = "NEQ"  # Not equal
    GT = "GT"  # Greater than
    LT = "LT"  # Less than
    GTE = "GTE"  # Greater than or equal
    LTE = "LTE"  # Less than or equal
    CONTAINS = "CONTAINS"  # Contains substring or element
    IN = "IN"  # Value in set
    LIKE = "LIKE"  # Simple pattern match (case-sensitive)
    ILIKE = "ILIKE"  # Simple pattern match (case-insensitive)
    SIMILAR = "SIMILAR"  # Vector similarity search


class LogicOperator(StrEnum):
    """Logic operators for combining predicates."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class IssueSeverity(StrEnum):
    """Severity levels for validation issues."""

    BLOCKING = "BLOCKING"  # Execution will fail; must be fixed
    WARNING = "WARNING"  # Execution will proceed but with side effects


class ConsistencyLevel(StrEnum):
    """Data consistency levels for execution results."""

    STRONG = "STRONG"
    EVENTUAL = "EVENTUAL"


class FieldType(StrEnum):
    """Supported field data types."""

    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    VECTOR = "VECTOR"
    BLOB = "BLOB"
    JSON = "JSON"


class PredicateUsage(StrEnum):
    """Predicate usage requirement."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class ValidationIssueCode(StrEnum):
    """Validation issue codes."""

    MISSING_REQUIRED_PREDICATE = "MISSING_REQUIRED_PREDICATE"
    INVALID_FORMAT = "INVALID_FORMAT"
    FIELD_NOT_PERMITTED = "FIELD_NOT_PERMITTED"
    FIELD_NOT_FOUND = "FIELD_NOT_FOUND"
    INVALID_OPERATOR = "INVALID_OPERATOR"
    INVALID_VALUE = "INVALID_VALUE"
    CARDINALITY_EXCEEDED = "CARDINALITY_EXCEEDED"


# =============================================================================
# Predicate Types
# =============================================================================


class SimilarValue(ADPModel):
    """Structured value for SIMILAR operator (vector similarity search)."""

    text: str | None = PydanticField(
        default=None, description="Text content to search for similarity"
    )
    blob: str | None = PydanticField(
        default=None, description="Binary content as Base64 or URI reference"
    )
    top: int | None = PydanticField(default=None, description="Maximum number of results to return")
    threshold: float | None = PydanticField(
        default=None, description="Similarity threshold (0.0 to 1.0)"
    )
    distance_function: str | None = PydanticField(
        default=None,
        description="Distance function (e.g., COSINE, L2, INNER_PRODUCT)",
    )


PredicateValue = str | int | float | bool | list[str | int | float | bool] | SimilarValue
"""Value types allowed in predicates. explicitly includes float per user request."""


class Predicate(ADPModel):
    """A single predicate in an Intent IR."""

    field_id: str = PydanticField(..., description="The field identifier to filter on")
    op: PredicateOperator = PydanticField(..., description="The comparison operator")
    value: PredicateValue = PydanticField(..., description="The value to compare against")


class IdentityPredicate(ADPModel):
    """An identity predicate used for unique key lookups. Only allows EQ operator."""

    field_id: str = PydanticField(..., description="The field identifier to filter on")
    op: Literal["EQ"] = PydanticField(
        default="EQ", description="The comparison operator (must be EQ)"
    )
    value: str | int | bool = PydanticField(..., description="The value to compare against")


class PredicateGroup(ADPModel):
    """A group of predicates with a logic operator."""

    op: LogicOperator = PydanticField(..., description="The logic operator to use")
    predicates: list[Union["PredicateGroup", Predicate]] = PydanticField(
        ..., description="The predicates to apply"
    )


# =============================================================================
# Initialization Types
# =============================================================================


class Implementation(ADPModel):
    """Describes the ADP implementation."""

    name: str = PydanticField(..., description="Name of the implementation")
    version: str = PydanticField(..., description="Version of the implementation")


class ClientCapabilities(ADPModel):
    """Capabilities a client may support."""

    model_config = ConfigDict(extra="allow")

    experimental: dict[str, dict[str, Any]] | None = PydanticField(
        default=None, description="Experimental, non-standard capabilities"
    )


class ServerCapabilities(ADPModel):
    """Capabilities that a server may support."""

    model_config = ConfigDict(extra="allow")

    experimental: dict[str, dict[str, Any]] | None = PydanticField(
        default=None, description="Experimental, non-standard capabilities"
    )
    supported_intent_classes: list[IntentClass] | None = PydanticField(
        default=None,
        description="Supported intent classes by this server",
    )


class InitializeRequestParams(RequestParams):
    """Parameters for an adp.initialize request."""

    # Needs to enable auto-alias locally since it inherits from RequestParams (BaseModel)
    # OR we can make it inherit from ADPModel + RequestParams mixin style?
    # Simpler: Just define config here too or make RequestParams inherit from ADPModel?
    # WAIT: RequestParams is now pure BaseModel in jsonrpc.py (no auto alias).
    # But InitializeRequestParams needs auto-aliasing for `protocol_version` -> `protocolVersion`.
    # So InitializeRequestParams MUST have the config.
    # IN FACT: It's better if RequestParams was just a base class.
    # Let's override Config in InitializeRequestParams.

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    protocol_version: str = PydanticField(
        ...,
        description="The latest version of the ADP protocol that the client supports",
    )
    capabilities: ClientCapabilities = PydanticField(..., description="Client capabilities")
    client_info: Implementation = PydanticField(
        ..., description="Information about the client implementation"
    )


class InitializeRequest(ADPModel):
    """Request sent from the client to the server when it first connects."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.initialize"] = PydanticField(default="adp.initialize")
    params: InitializeRequestParams


class InitializeResult(Result):
    """Response to an initialize request from the server."""

    # Result -> BaseModel. We need auto-aliasing here too.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    protocol_version: str = PydanticField(
        ...,
        description="The version of the ADP protocol that the server wants to use",
    )
    capabilities: ServerCapabilities = PydanticField(..., description="Server capabilities")
    server_info: Implementation = PydanticField(
        ..., description="Information about the server implementation"
    )
    instructions: str | None = PydanticField(
        default=None, description="Instructions describing how to use the server and its features"
    )


# =============================================================================
# Ping Types
# =============================================================================


class PingRequest(ADPModel):
    """A ping to check that the other party is still alive."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.ping"] = PydanticField(default="adp.ping")
    params: RequestParams | None = PydanticField(default=None)


EmptyResult = Result
"""A response that indicates success but carries no data."""


# =============================================================================
# Pagination Types
# =============================================================================


class PaginatedRequestParams(RequestParams):
    """Common parameters for paginated requests."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",  # RequestParams allows extra
    )

    cursor: Cursor | None = PydanticField(
        default=None, description="An opaque token representing the current pagination position"
    )


class PaginatedResult(Result):
    """Common result type for paginated responses."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    next_cursor: Cursor | None = PydanticField(
        default=None,
        description="An opaque token representing the pagination position after the last result",
    )


# =============================================================================
# Discover Types
# =============================================================================


class DiscoverFilter(ADPModel):
    """Filter criteria for the DISCOVER operation."""

    domain_prefix: str | None = PydanticField(
        default=None, description="Filter resources by domain prefix"
    )
    intent_class: IntentClass | None = PydanticField(
        default=None, description="Filter resources by intent class"
    )
    keyword: str | None = PydanticField(
        default=None, description="Filter resources by keyword search"
    )


class DiscoverRequestParams(PaginatedRequestParams):
    """Parameters for the adp.discover request."""

    filter: DiscoverFilter | None = PydanticField(
        default=None, description="Optional filters to narrow down the resource list"
    )


class DiscoverRequest(ADPModel):
    """Request to browse available resources."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.discover"] = PydanticField(default="adp.discover")
    params: DiscoverRequestParams | None = PydanticField(default=None)


class Resource(ADPModel):
    """Base resource information shared between protocol responses and curation manifests."""

    resource_id: ResourceId | None = PydanticField(
        default=None,
        description="The unique domain-qualified identifier for this resource",
    )
    version: int | None = PydanticField(
        default=None, description="The version number of this resource's schema"
    )
    intent_classes: list[IntentClass] | None = PydanticField(
        default=None, description="The intent classes this resource supports"
    )
    description: str | None = PydanticField(
        default=None, description="A brief description of the resource"
    )
    semantic_description: str | None = PydanticField(
        default=None,
        description="A detailed semantic description of the resource",
    )
    tags: list[str] | None = PydanticField(
        default=None, description="Tags for categorization and filtering"
    )


class DiscoverResult(PaginatedResult):
    """Result of the adp.discover request."""

    resources: list[Resource] = PydanticField(
        ..., description="List of discovered resources matching the filter criteria"
    )


# =============================================================================
# Describe Types
# =============================================================================


class FieldMetadata(ADPModel):
    """Metadata about a field's characteristics."""

    model_config = ConfigDict(extra="allow")

    cardinality: int | str | None = PydanticField(
        default=None, description="Number of unique values in this field"
    )
    format: str | None = PydanticField(default=None, description="Expected format pattern")
    whitelist_only: bool | None = PydanticField(
        default=None,
        description="If true, only values from provided samples are valid",
    )
    hint: str | None = PydanticField(
        default=None, description="A hint for the Agent about how to use this field"
    )
    vector: dict[str, Any] | None = PydanticField(
        default=None, description="For VECTOR fields, specifies dimensions and distance function"
    )
    samples: list[Any] | None = PydanticField(
        default=None, description="Sample values for this field"
    )


class Field(ADPModel):
    """Definition of a single field in a resource."""

    field_id: str = PydanticField(..., description="The field identifier")
    type: FieldType = PydanticField(..., description="The data type of this field")
    description: str | None = PydanticField(
        default=None, description="Human-readable description of the field"
    )
    samples: list[Any] | None = PydanticField(
        default=None, description="Sample values for this field"
    )
    is_masked: bool | None = PydanticField(
        default=None, description="If true, this field is masked/redacted"
    )
    is_searchable: bool | None = PydanticField(
        default=None,
        description="If true, this field supports similarity search",
    )
    metadata: FieldMetadata | None = PydanticField(
        default=None, description="Additional metadata about the field"
    )


class PredicateCapability(ADPModel):
    """Definition of a predicate capability for a field."""

    field_id: str = PydanticField(..., description="The field this predicate applies to")
    usage: PredicateUsage = PydanticField(
        ..., description="Whether this predicate is required or optional"
    )
    operators: list[PredicateOperator] = PydanticField(
        ..., description="Allowed operators for this predicate"
    )


class ProjectionCapability(ADPModel):
    """Definition of a projection capability."""

    field_id: str = PydanticField(..., description="The field that can be projected")


class MutableCapability(ADPModel):
    """Definition of a mutable field capability (for WRITE operations)."""

    field_id: str = PydanticField(..., description="The field that can be mutated")
    constraints: dict[str, Any] | None = PydanticField(
        default=None, description="Constraints on the mutation"
    )


class Capabilities(ADPModel):
    """Capabilities available for a resource."""

    predicates: list[PredicateCapability] | None = PydanticField(
        default=None, description="Available predicate capabilities"
    )
    projections: list[ProjectionCapability] | None = PydanticField(
        default=None, description="Available projection capabilities"
    )
    mutables: list[MutableCapability] | None = PydanticField(
        default=None, description="Available mutable field capabilities"
    )


class UsageContract(ADPModel):
    """The usage contract returned by DESCRIBE."""

    fields: list[Field] = PydanticField(..., description="Field definitions for this resource")
    capabilities: Capabilities = PydanticField(
        ..., description="Capabilities available for this resource and intent"
    )


class DescribeRequestParams(PaginatedRequestParams):
    """Parameters for the adp.describe request."""

    resource_id: ResourceId = PydanticField(
        ..., description="The unique identifier of the resource to describe"
    )
    intent_class: IntentClass = PydanticField(
        ..., description="The intent class the Agent plans to use"
    )
    version: int | None = PydanticField(
        default=None, description="The version of the resource to describe"
    )


class DescribeRequest(ADPModel):
    """Request to get the usage contract for a resource."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.describe"] = PydanticField(default="adp.describe")
    params: DescribeRequestParams


class DescribeResult(PaginatedResult):
    """Result of the adp.describe request."""

    resource_id: ResourceId = PydanticField(
        ..., description="The resource's full qualified identifier"
    )
    version: int = PydanticField(
        ..., description="The version of the resource schema that was returned"
    )
    intent_class: IntentClass = PydanticField(
        ..., description="The intent class this contract applies to"
    )
    usage_contract: UsageContract = PydanticField(
        ..., description="The usage contract for this resource and intent"
    )


# =============================================================================
# Intent Types
# =============================================================================


class LookupIntent(ADPModel):
    """Intent for retrieving a single entity by its unique identifier."""

    intent_class: Literal["LOOKUP"] = PydanticField(
        default="LOOKUP", description="Intent class type"
    )
    key: IdentityPredicate = PydanticField(
        ..., description="The identity predicate specifying the unique key to lookup"
    )
    projections: list[str] | None = PydanticField(default=None, description="Fields to project")


class SortOrder(ADPModel):
    """Sort order for a field."""

    direction: Literal["ASC", "DESC"] = PydanticField(
        ..., description="The direction of the sort order"
    )
    field_id: str = PydanticField(..., description="The field to sort by")


class QueryIntent(ADPModel):
    """Intent for retrieving a set of entities based on criteria."""

    intent_class: Literal["QUERY"] = PydanticField(default="QUERY", description="Intent class type")
    predicates: PredicateGroup = PydanticField(..., description="Predicates for filtering data")
    projections: list[str] | None = PydanticField(default=None, description="Fields to project")
    order_by: list[SortOrder] | None = PydanticField(
        default=None, description="Fields to order results by"
    )
    limit: int | None = PydanticField(
        default=None, description="The maximum number of results to return"
    )


class IngestIntent(ADPModel):
    """Intent for creating or appending new data."""

    intent_class: Literal["INGEST"] = PydanticField(
        default="INGEST", description="Intent class type"
    )
    payload: list[dict[str, Any]] = PydanticField(..., description="The data payload to ingest")


class ReviseIntent(ADPModel):
    """Intent for updating existing data."""

    intent_class: Literal["REVISE"] = PydanticField(
        default="REVISE", description="Intent class type"
    )
    predicates: PredicateGroup = PydanticField(
        ..., description="Predicates to identify the records to update"
    )
    payload: dict[str, Any] = PydanticField(
        ..., description="The data payload containing the fields to update"
    )


Intent = Annotated[
    LookupIntent | QueryIntent | IngestIntent | ReviseIntent,
    PydanticField(discriminator="intent_class"),
]
"""The Intent structure used in VALIDATE and EXECUTE operations."""


# =============================================================================
# Validate Types
# =============================================================================


class ValidationIssue(ADPModel):
    """A single validation issue."""

    code: ValidationIssueCode = PydanticField(..., description="The type of validation issue")
    field: str | None = PydanticField(
        default=None, description="The field associated with this issue"
    )
    severity: IssueSeverity = PydanticField(..., description="Severity of this issue")
    message: str = PydanticField(..., description="Human-readable message describing the issue")
    correction_hint: str | None = PydanticField(
        default=None, description="Correction hint for the Agent"
    )


class ValidateRequestParams(RequestParams):
    """Parameters for the adp.validate request."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",  # RequestParams allows extra
    )

    resource_id: ResourceId = PydanticField(..., description="The resource to validate against")
    intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent = PydanticField(
        ..., description="The Intent to validate"
    )


class ValidateRequest(ADPModel):
    """Request to validate an Intent IR before execution."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.validate"] = PydanticField(default="adp.validate")
    params: ValidateRequestParams


class ValidateResult(Result):
    """Result of the adp.validate request."""

    valid: bool = PydanticField(..., description="Whether the Intent IR is valid")
    issues: list[ValidationIssue] | None = PydanticField(
        default=None, description="List of validation issues, if any"
    )


# =============================================================================
# Execute Types
# =============================================================================


class ExecuteRequestParams(PaginatedRequestParams):
    """Parameters for the adp.execute request."""

    resource_id: ResourceId = PydanticField(..., description="The resource to execute against")
    intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent = PydanticField(
        ..., description="The Intent to execute"
    )


class ExecuteRequest(ADPModel):
    """Request to execute an Intent IR."""

    jsonrpc: Literal["2.0"] = PydanticField(default="2.0")
    id: RequestId
    method: Literal["adp.execute"] = PydanticField(default="adp.execute")
    params: ExecuteRequestParams


class ExecutionMetadata(ADPModel):
    """Metadata about execution performance and characteristics."""

    duration_ms: int | None = PydanticField(
        default=None, description="Time taken to execute in milliseconds"
    )
    source_system: str | None = PydanticField(
        default=None, description="The backend system that served the request"
    )
    consistency: ConsistencyLevel | None = PydanticField(
        default=None, description="Data consistency level of the result"
    )


class ExecuteResult(PaginatedResult):
    """Result of the adp.execute request."""

    results: list[dict[str, Any]] = PydanticField(..., description="The result data")
    execution_metadata: ExecutionMetadata | None = PydanticField(
        default=None,
        description="Additional metadata about the execution",
    )


# Enable forward references for self-referencing models
PredicateGroup.model_rebuild()
