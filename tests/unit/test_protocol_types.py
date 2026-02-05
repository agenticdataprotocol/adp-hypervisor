"""Unit tests for ADP protocol type definitions."""

import pytest
from pydantic import ValidationError

from adp_hypervisor.protocol import (
    EXECUTION_FAILED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RESOURCE_NOT_FOUND,
    UNAUTHORIZED,
    VALIDATION_FAILED,
    ADPError,
    Capabilities,
    ClientCapabilities,
    ConsistencyLevel,
    DescribeRequestParams,
    DescribeResult,
    DiscoverFilter,
    DiscoverRequestParams,
    DiscoverResult,
    ExecuteRequestParams,
    ExecuteResult,
    ExecutionFailedError,
    ExecutionMetadata,
    Field,
    FieldMetadata,
    FieldType,
    IdentityPredicate,
    Implementation,
    IngestIntent,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
    IntentClass,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    IssueSeverity,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCResultResponse,
    LogicOperator,
    LookupIntent,
    MethodNotFoundError,
    MutableCapability,
    PaginatedRequestParams,
    PaginatedResult,
    ParseError,
    PingRequest,
    Predicate,
    PredicateCapability,
    PredicateGroup,
    PredicateOperator,
    PredicateUsage,
    ProjectionCapability,
    QueryIntent,
    RequestParams,
    Resource,
    ResourceNotFoundError,
    Result,
    ReviseIntent,
    ServerCapabilities,
    SimilarValue,
    SortOrder,
    UnauthorizedError,
    UsageContract,
    ValidateRequestParams,
    ValidateResult,
    ValidationFailedError,
    ValidationIssue,
    ValidationIssueCode,
    error_from_code,
)


class TestConstants:
    """Tests for protocol constants."""

    def test_protocol_version(self) -> None:
        assert LATEST_PROTOCOL_VERSION == "2026-01-20"

    def test_jsonrpc_version(self) -> None:
        assert JSONRPC_VERSION == "2.0"


class TestEnums:
    """Tests for protocol enums."""

    def test_intent_class_values(self) -> None:
        assert IntentClass.LOOKUP.value == "LOOKUP"
        assert IntentClass.QUERY.value == "QUERY"
        assert IntentClass.INGEST.value == "INGEST"
        assert IntentClass.REVISE.value == "REVISE"
        assert IntentClass.WILDCARD.value == "*"

    def test_predicate_operator_values(self) -> None:
        assert PredicateOperator.EQ.value == "EQ"
        assert PredicateOperator.NEQ.value == "NEQ"
        assert PredicateOperator.GT.value == "GT"
        assert PredicateOperator.LT.value == "LT"
        assert PredicateOperator.GTE.value == "GTE"
        assert PredicateOperator.LTE.value == "LTE"
        assert PredicateOperator.CONTAINS.value == "CONTAINS"
        assert PredicateOperator.IN.value == "IN"
        assert PredicateOperator.LIKE.value == "LIKE"
        assert PredicateOperator.ILIKE.value == "ILIKE"
        assert PredicateOperator.SIMILAR.value == "SIMILAR"

    def test_logic_operator_values(self) -> None:
        assert LogicOperator.AND.value == "AND"
        assert LogicOperator.OR.value == "OR"
        assert LogicOperator.NOT.value == "NOT"

    def test_issue_severity_values(self) -> None:
        assert IssueSeverity.BLOCKING.value == "BLOCKING"
        assert IssueSeverity.WARNING.value == "WARNING"

    def test_consistency_level_values(self) -> None:
        assert ConsistencyLevel.STRONG.value == "STRONG"
        assert ConsistencyLevel.EVENTUAL.value == "EVENTUAL"

    def test_field_type_values(self) -> None:
        assert FieldType.STRING.value == "STRING"
        assert FieldType.INTEGER.value == "INTEGER"
        assert FieldType.FLOAT.value == "FLOAT"
        assert FieldType.BOOLEAN.value == "BOOLEAN"
        assert FieldType.DATE.value == "DATE"
        assert FieldType.TIMESTAMP.value == "TIMESTAMP"
        assert FieldType.VECTOR.value == "VECTOR"
        assert FieldType.BLOB.value == "BLOB"
        assert FieldType.JSON.value == "JSON"

    def test_predicate_usage_values(self) -> None:
        assert PredicateUsage.REQUIRED.value == "REQUIRED"
        assert PredicateUsage.OPTIONAL.value == "OPTIONAL"

    def test_validation_issue_code_values(self) -> None:
        assert ValidationIssueCode.MISSING_REQUIRED_PREDICATE.value == "MISSING_REQUIRED_PREDICATE"
        assert ValidationIssueCode.INVALID_FORMAT.value == "INVALID_FORMAT"
        assert ValidationIssueCode.FIELD_NOT_PERMITTED.value == "FIELD_NOT_PERMITTED"
        assert ValidationIssueCode.FIELD_NOT_FOUND.value == "FIELD_NOT_FOUND"
        assert ValidationIssueCode.INVALID_OPERATOR.value == "INVALID_OPERATOR"
        assert ValidationIssueCode.INVALID_VALUE.value == "INVALID_VALUE"
        assert ValidationIssueCode.CARDINALITY_EXCEEDED.value == "CARDINALITY_EXCEEDED"


class TestJSONRPCTypes:
    """Tests for JSON-RPC types."""

    def test_jsonrpc_error(self) -> None:
        error = JSONRPCError(code=-32600, message="Invalid request")
        assert error.code == -32600
        assert error.message == "Invalid request"
        assert error.data is None

    def test_jsonrpc_error_with_data(self) -> None:
        error = JSONRPCError(code=-32602, message="Invalid params", data={"field": "missing"})
        assert error.code == -32602
        assert error.data == {"field": "missing"}

    def test_jsonrpc_request(self) -> None:
        request = JSONRPCRequest(id=1, method="adp.ping")
        assert request.jsonrpc == "2.0"
        assert request.id == 1
        assert request.method == "adp.ping"
        assert request.params is None

    def test_jsonrpc_request_with_params(self) -> None:
        request = JSONRPCRequest(id="req-123", method="adp.discover", params={"cursor": "abc"})
        assert request.id == "req-123"
        assert request.params == {"cursor": "abc"}

    def test_jsonrpc_result_response(self) -> None:
        response = JSONRPCResultResponse(id=1, result={"valid": True})
        assert response.jsonrpc == "2.0"
        assert response.id == 1
        assert response.result == {"valid": True}

    def test_jsonrpc_error_response(self) -> None:
        error = JSONRPCError(code=-32600, message="Invalid request")
        response = JSONRPCErrorResponse(error=error)
        assert response.jsonrpc == "2.0"
        assert response.id is None
        assert response.error.code == -32600

    def test_request_params_with_meta(self) -> None:
        params = RequestParams.model_validate({"_meta": {"progressToken": "token-123"}})
        assert params.meta_ == {"progressToken": "token-123"}

    def test_result_extra_fields(self) -> None:
        result = Result.model_validate({"custom_field": "value"})
        assert result.custom_field == "value"  # type: ignore[attr-defined]


class TestPredicateTypes:
    """Tests for predicate types."""

    def test_similar_value(self) -> None:
        similar = SimilarValue(text="hello world", top=10, threshold=0.8)
        assert similar.text == "hello world"
        assert similar.top == 10
        assert similar.threshold == 0.8

    def test_similar_value_with_distance_function(self) -> None:
        similar = SimilarValue.model_validate({"text": "query", "distanceFunction": "COSINE"})
        assert similar.distance_function == "COSINE"

    def test_predicate(self) -> None:
        pred = Predicate.model_validate({"fieldId": "name", "op": "EQ", "value": "John"})
        assert pred.field_id == "name"
        assert pred.op == PredicateOperator.EQ
        assert pred.value == "John"

    def test_predicate_with_list_value(self) -> None:
        pred = Predicate.model_validate({"fieldId": "status", "op": "IN", "value": ["A", "B", "C"]})
        assert pred.op == PredicateOperator.IN
        assert pred.value == ["A", "B", "C"]

    def test_identity_predicate(self) -> None:
        pred = IdentityPredicate.model_validate({"fieldId": "id", "op": "EQ", "value": 123})
        assert pred.field_id == "id"
        assert pred.op == "EQ"
        assert pred.value == 123

    def test_identity_predicate_requires_eq(self) -> None:
        with pytest.raises(ValidationError):
            IdentityPredicate.model_validate({"fieldId": "id", "op": "GT", "value": 123})

    def test_predicate_group(self) -> None:
        group = PredicateGroup.model_validate(
            {
                "op": "AND",
                "predicates": [
                    {"fieldId": "name", "op": "EQ", "value": "John"},
                    {"fieldId": "age", "op": "GT", "value": 18},
                ],
            }
        )
        assert group.op == LogicOperator.AND
        assert len(group.predicates) == 2

    def test_nested_predicate_group(self) -> None:
        group = PredicateGroup.model_validate(
            {
                "op": "OR",
                "predicates": [
                    {
                        "op": "AND",
                        "predicates": [
                            {"fieldId": "a", "op": "EQ", "value": 1},
                            {"fieldId": "b", "op": "EQ", "value": 2},
                        ],
                    },
                    {"fieldId": "c", "op": "EQ", "value": 3},
                ],
            }
        )
        assert group.op == LogicOperator.OR
        assert len(group.predicates) == 2
        assert isinstance(group.predicates[0], PredicateGroup)


class TestInitializeTypes:
    """Tests for initialize types."""

    def test_implementation(self) -> None:
        impl = Implementation(name="ADP-Hypervisor", version="0.1.0")
        assert impl.name == "ADP-Hypervisor"
        assert impl.version == "0.1.0"

    def test_client_capabilities(self) -> None:
        caps = ClientCapabilities()
        assert caps.experimental is None

    def test_client_capabilities_with_experimental(self) -> None:
        caps = ClientCapabilities(experimental={"feature1": {"enabled": True}})
        assert caps.experimental == {"feature1": {"enabled": True}}

    def test_server_capabilities(self) -> None:
        caps = ServerCapabilities.model_validate(
            {
                "supportedIntentClasses": ["QUERY", "LOOKUP"],
            }
        )
        assert caps.supported_intent_classes == [IntentClass.QUERY, IntentClass.LOOKUP]

    def test_initialize_request_params(self) -> None:
        params = InitializeRequestParams.model_validate(
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"},
            }
        )
        assert params.protocol_version == "2026-01-20"
        assert params.client_info.name == "TestClient"

    def test_initialize_request(self) -> None:
        request = InitializeRequest.model_validate(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "adp.initialize",
                "params": {
                    "protocolVersion": "2026-01-20",
                    "capabilities": {},
                    "clientInfo": {"name": "Client", "version": "1.0"},
                },
            }
        )
        assert request.method == "adp.initialize"
        assert request.params.protocol_version == "2026-01-20"

    def test_initialize_result(self) -> None:
        result = InitializeResult.model_validate(
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {"supportedIntentClasses": ["*"]},
                "serverInfo": {"name": "ADP-Hypervisor", "version": "0.1.0"},
                "instructions": "Use discover to find resources",
            }
        )
        assert result.protocol_version == "2026-01-20"
        assert result.server_info.name == "ADP-Hypervisor"
        assert result.instructions == "Use discover to find resources"


class TestPingTypes:
    """Tests for ping types."""

    def test_ping_request(self) -> None:
        request = PingRequest(id=1)
        assert request.method == "adp.ping"
        assert request.params is None


class TestPaginationTypes:
    """Tests for pagination types."""

    def test_paginated_request_params(self) -> None:
        params = PaginatedRequestParams(cursor="abc123")
        assert params.cursor == "abc123"

    def test_paginated_result(self) -> None:
        result = PaginatedResult.model_validate({"nextCursor": "next-page"})
        assert result.next_cursor == "next-page"


class TestDiscoverTypes:
    """Tests for discover types."""

    def test_discover_filter(self) -> None:
        filter_ = DiscoverFilter.model_validate(
            {
                "domainPrefix": "com.acme",
                "intentClass": "QUERY",
                "keyword": "finance",
            }
        )
        assert filter_.domain_prefix == "com.acme"
        assert filter_.intent_class == IntentClass.QUERY
        assert filter_.keyword == "finance"

    def test_discover_request_params(self) -> None:
        params = DiscoverRequestParams.model_validate(
            {
                "filter": {"domainPrefix": "com.acme"},
                "cursor": "page2",
            }
        )
        assert params.filter is not None
        assert params.filter.domain_prefix == "com.acme"
        assert params.cursor == "page2"

    def test_resource(self) -> None:
        resource = Resource.model_validate(
            {
                "resourceId": "com.acme.finance:bank_failures",
                "version": 1,
                "intentClasses": ["QUERY", "LOOKUP"],
                "description": "Failed bank data",
                "tags": ["PII-FREE", "FINANCE"],
            }
        )
        assert resource.resource_id == "com.acme.finance:bank_failures"
        assert resource.version == 1
        assert resource.intent_classes == [IntentClass.QUERY, IntentClass.LOOKUP]
        assert resource.tags == ["PII-FREE", "FINANCE"]

    def test_discover_result(self) -> None:
        result = DiscoverResult.model_validate(
            {
                "resources": [
                    {"resourceId": "res1", "description": "Resource 1"},
                    {"resourceId": "res2", "description": "Resource 2"},
                ],
                "nextCursor": "page2",
            }
        )
        assert len(result.resources) == 2
        assert result.next_cursor == "page2"


class TestDescribeTypes:
    """Tests for describe types."""

    def test_field_metadata(self) -> None:
        metadata = FieldMetadata.model_validate(
            {
                "cardinality": 1000,
                "format": "YYYY-MM-DD",
                "whitelistOnly": True,
                "hint": "Use ISO format",
            }
        )
        assert metadata.cardinality == 1000
        assert metadata.format == "YYYY-MM-DD"
        assert metadata.whitelist_only is True
        assert metadata.hint == "Use ISO format"

    def test_field(self) -> None:
        field = Field.model_validate(
            {
                "fieldId": "name",
                "type": "STRING",
                "description": "User name",
                "samples": ["John", "Jane"],
                "isMasked": False,
                "isSearchable": True,
            }
        )
        assert field.field_id == "name"
        assert field.type == FieldType.STRING
        assert field.samples == ["John", "Jane"]
        assert field.is_masked is False
        assert field.is_searchable is True

    def test_predicate_capability(self) -> None:
        cap = PredicateCapability.model_validate(
            {
                "fieldId": "status",
                "usage": "REQUIRED",
                "operators": ["EQ", "IN"],
            }
        )
        assert cap.field_id == "status"
        assert cap.usage == PredicateUsage.REQUIRED
        assert cap.operators == [PredicateOperator.EQ, PredicateOperator.IN]

    def test_projection_capability(self) -> None:
        cap = ProjectionCapability.model_validate({"fieldId": "name"})
        assert cap.field_id == "name"

    def test_mutable_capability(self) -> None:
        cap = MutableCapability.model_validate(
            {
                "fieldId": "status",
                "constraints": {"maxLength": 100},
            }
        )
        assert cap.field_id == "status"
        assert cap.constraints == {"maxLength": 100}

    def test_capabilities(self) -> None:
        caps = Capabilities.model_validate(
            {
                "predicates": [{"fieldId": "id", "usage": "REQUIRED", "operators": ["EQ"]}],
                "projections": [{"fieldId": "name"}],
            }
        )
        assert len(caps.predicates or []) == 1
        assert len(caps.projections or []) == 1

    def test_usage_contract(self) -> None:
        contract = UsageContract.model_validate(
            {
                "fields": [{"fieldId": "id", "type": "INTEGER"}],
                "capabilities": {
                    "predicates": [{"fieldId": "id", "usage": "OPTIONAL", "operators": ["EQ"]}],
                },
            }
        )
        assert len(contract.fields) == 1
        assert contract.capabilities.predicates is not None

    def test_describe_request_params(self) -> None:
        params = DescribeRequestParams.model_validate(
            {
                "resourceId": "com.acme:users",
                "intentClass": "QUERY",
                "version": 2,
            }
        )
        assert params.resource_id == "com.acme:users"
        assert params.intent_class == IntentClass.QUERY
        assert params.version == 2

    def test_describe_result(self) -> None:
        result = DescribeResult.model_validate(
            {
                "resourceId": "com.acme:users",
                "version": 1,
                "intentClass": "QUERY",
                "usageContract": {
                    "fields": [{"fieldId": "id", "type": "INTEGER"}],
                    "capabilities": {"predicates": []},
                },
            }
        )
        assert result.resource_id == "com.acme:users"
        assert result.version == 1
        assert result.intent_class == IntentClass.QUERY


class TestIntentTypes:
    """Tests for intent types."""

    def test_lookup_intent(self) -> None:
        intent = LookupIntent.model_validate(
            {
                "intentClass": "LOOKUP",
                "key": {"fieldId": "id", "op": "EQ", "value": 123},
                "projections": ["name", "email"],
            }
        )
        assert intent.intent_class == "LOOKUP"
        assert intent.key.field_id == "id"
        assert intent.projections == ["name", "email"]

    def test_sort_order(self) -> None:
        order = SortOrder.model_validate({"direction": "ASC", "fieldId": "name"})
        assert order.direction == "ASC"
        assert order.field_id == "name"

    def test_query_intent(self) -> None:
        intent = QueryIntent.model_validate(
            {
                "intentClass": "QUERY",
                "predicates": {
                    "op": "AND",
                    "predicates": [{"fieldId": "status", "op": "EQ", "value": "active"}],
                },
                "projections": ["id", "name"],
                "orderBy": [{"direction": "DESC", "fieldId": "created_at"}],
                "limit": 100,
            }
        )
        assert intent.intent_class == "QUERY"
        assert intent.predicates.op == LogicOperator.AND
        assert intent.limit == 100

    def test_ingest_intent(self) -> None:
        intent = IngestIntent.model_validate(
            {
                "intentClass": "INGEST",
                "payload": [
                    {"name": "John", "age": 30},
                    {"name": "Jane", "age": 25},
                ],
            }
        )
        assert intent.intent_class == "INGEST"
        assert len(intent.payload) == 2

    def test_revise_intent(self) -> None:
        intent = ReviseIntent.model_validate(
            {
                "intentClass": "REVISE",
                "predicates": {
                    "op": "AND",
                    "predicates": [{"fieldId": "id", "op": "EQ", "value": 123}],
                },
                "payload": {"status": "inactive"},
            }
        )
        assert intent.intent_class == "REVISE"
        assert intent.payload == {"status": "inactive"}


class TestValidateTypes:
    """Tests for validate types."""

    def test_validation_issue(self) -> None:
        issue = ValidationIssue.model_validate(
            {
                "code": "FIELD_NOT_FOUND",
                "field": "unknown_field",
                "severity": "BLOCKING",
                "message": "Field not found in schema",
                "correctionHint": "Check available fields with describe",
            }
        )
        assert issue.code == ValidationIssueCode.FIELD_NOT_FOUND
        assert issue.severity == IssueSeverity.BLOCKING
        assert issue.correction_hint == "Check available fields with describe"

    def test_validate_request_params(self) -> None:
        params = ValidateRequestParams.model_validate(
            {
                "resourceId": "com.acme:users",
                "intent": {
                    "intentClass": "LOOKUP",
                    "key": {"fieldId": "id", "op": "EQ", "value": 1},
                },
            }
        )
        assert params.resource_id == "com.acme:users"
        assert isinstance(params.intent, LookupIntent)

    def test_validate_result_valid(self) -> None:
        result = ValidateResult.model_validate({"valid": True})
        assert result.valid is True
        assert result.issues is None

    def test_validate_result_invalid(self) -> None:
        result = ValidateResult.model_validate(
            {
                "valid": False,
                "issues": [
                    {
                        "code": "MISSING_REQUIRED_PREDICATE",
                        "field": "id",
                        "severity": "BLOCKING",
                        "message": "Required predicate missing",
                    }
                ],
            }
        )
        assert result.valid is False
        assert len(result.issues or []) == 1


class TestExecuteTypes:
    """Tests for execute types."""

    def test_execute_request_params(self) -> None:
        params = ExecuteRequestParams.model_validate(
            {
                "resourceId": "com.acme:users",
                "intent": {
                    "intentClass": "QUERY",
                    "predicates": {
                        "op": "AND",
                        "predicates": [{"fieldId": "status", "op": "EQ", "value": "active"}],
                    },
                },
                "cursor": "page2",
            }
        )
        assert params.resource_id == "com.acme:users"
        assert isinstance(params.intent, QueryIntent)

    def test_execution_metadata(self) -> None:
        metadata = ExecutionMetadata.model_validate(
            {
                "durationMs": 150,
                "sourceSystem": "PostgreSQL",
                "consistency": "STRONG",
            }
        )
        assert metadata.duration_ms == 150
        assert metadata.source_system == "PostgreSQL"
        assert metadata.consistency == ConsistencyLevel.STRONG

    def test_execute_result(self) -> None:
        result = ExecuteResult.model_validate(
            {
                "results": [{"id": 1, "name": "John"}, {"id": 2, "name": "Jane"}],
                "executionMetadata": {"durationMs": 100},
                "nextCursor": "page2",
            }
        )
        assert len(result.results) == 2
        assert result.execution_metadata is not None
        assert result.execution_metadata.duration_ms == 100
        assert result.next_cursor == "page2"


class TestErrorCodes:
    """Tests for error code constants."""

    def test_standard_error_codes(self) -> None:
        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602
        assert INTERNAL_ERROR == -32603

    def test_adp_error_codes(self) -> None:
        assert RESOURCE_NOT_FOUND == -32001
        assert VALIDATION_FAILED == -32002
        assert UNAUTHORIZED == -32003
        assert EXECUTION_FAILED == -32004


class TestADPErrors:
    """Tests for ADP error classes."""

    def test_adp_error_base(self) -> None:
        error = ADPError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.code == INTERNAL_ERROR

    def test_adp_error_to_dict(self) -> None:
        error = ADPError("Error message", data={"detail": "info"})
        error_dict = error.to_dict()
        assert error_dict["code"] == INTERNAL_ERROR
        assert error_dict["message"] == "Error message"
        assert error_dict["data"] == {"detail": "info"}

    def test_parse_error(self) -> None:
        error = ParseError()
        assert error.code == PARSE_ERROR
        assert str(error) == "Parse error"

    def test_parse_error_custom_message(self) -> None:
        error = ParseError("Invalid JSON at position 5")
        assert str(error) == "Invalid JSON at position 5"

    def test_invalid_request_error(self) -> None:
        error = InvalidRequestError()
        assert error.code == INVALID_REQUEST

    def test_method_not_found_error(self) -> None:
        error = MethodNotFoundError("Method 'unknown' not found")
        assert error.code == METHOD_NOT_FOUND
        assert str(error) == "Method 'unknown' not found"

    def test_invalid_params_error(self) -> None:
        error = InvalidParamsError(data={"missing": ["resourceId"]})
        assert error.code == INVALID_PARAMS
        assert error.data == {"missing": ["resourceId"]}

    def test_internal_error(self) -> None:
        error = InternalError()
        assert error.code == INTERNAL_ERROR

    def test_resource_not_found_error(self) -> None:
        error = ResourceNotFoundError("Resource 'com.acme:unknown' not found")
        assert error.code == RESOURCE_NOT_FOUND

    def test_validation_failed_error(self) -> None:
        error = ValidationFailedError(data={"issues": [{"code": "FIELD_NOT_FOUND"}]})
        assert error.code == VALIDATION_FAILED

    def test_unauthorized_error(self) -> None:
        error = UnauthorizedError()
        assert error.code == UNAUTHORIZED

    def test_execution_failed_error(self) -> None:
        error = ExecutionFailedError("Query timeout")
        assert error.code == EXECUTION_FAILED
        assert str(error) == "Query timeout"


class TestErrorFromCode:
    """Tests for error_from_code function."""

    def test_known_error_codes(self) -> None:
        assert isinstance(error_from_code(PARSE_ERROR), ParseError)
        assert isinstance(error_from_code(INVALID_REQUEST), InvalidRequestError)
        assert isinstance(error_from_code(METHOD_NOT_FOUND), MethodNotFoundError)
        assert isinstance(error_from_code(INVALID_PARAMS), InvalidParamsError)
        assert isinstance(error_from_code(INTERNAL_ERROR), InternalError)
        assert isinstance(error_from_code(RESOURCE_NOT_FOUND), ResourceNotFoundError)
        assert isinstance(error_from_code(VALIDATION_FAILED), ValidationFailedError)
        assert isinstance(error_from_code(UNAUTHORIZED), UnauthorizedError)
        assert isinstance(error_from_code(EXECUTION_FAILED), ExecutionFailedError)

    def test_unknown_error_code(self) -> None:
        error = error_from_code(-32099, "Custom error")
        assert isinstance(error, ADPError)
        assert error.code == -32099
        assert str(error) == "Custom error"

    def test_error_from_code_with_data(self) -> None:
        error = error_from_code(INVALID_PARAMS, "Missing field", data={"field": "name"})
        assert error.data == {"field": "name"}


class TestModelSerialization:
    """Tests for model serialization (JSON output)."""

    def test_initialize_result_serialization(self) -> None:
        result = InitializeResult.model_validate(
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {"supportedIntentClasses": ["QUERY", "LOOKUP"]},
                "serverInfo": {"name": "ADP-Hypervisor", "version": "0.1.0"},
            }
        )
        data = result.model_dump(by_alias=True, exclude_none=True)
        assert data["protocolVersion"] == "2026-01-20"
        assert data["serverInfo"]["name"] == "ADP-Hypervisor"
        assert "supportedIntentClasses" in data["capabilities"]

    def test_predicate_serialization(self) -> None:
        pred = Predicate.model_validate({"fieldId": "name", "op": "EQ", "value": "John"})
        data = pred.model_dump(by_alias=True)
        assert data["fieldId"] == "name"
        assert data["op"] == "EQ"

    def test_discover_result_serialization(self) -> None:
        result = DiscoverResult.model_validate(
            {
                "resources": [
                    {"resourceId": "com.acme:users", "intentClasses": ["QUERY"]},
                ],
                "nextCursor": "page2",
            }
        )
        data = result.model_dump(by_alias=True, exclude_none=True)
        assert data["resources"][0]["resourceId"] == "com.acme:users"
        assert data["nextCursor"] == "page2"
