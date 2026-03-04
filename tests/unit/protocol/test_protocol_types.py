"""Unit tests for ADP protocol type definitions."""

import unittest

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
    normalize_to_predicate_group,
)


class TestConstants(unittest.TestCase):
    """Tests for protocol constants."""

    def test_protocol_version(self) -> None:
        self.assertEqual(LATEST_PROTOCOL_VERSION, "2026-01-20")

    def test_jsonrpc_version(self) -> None:
        self.assertEqual(JSONRPC_VERSION, "2.0")


class TestEnums(unittest.TestCase):
    """Tests for protocol enums."""

    def test_intent_class_values(self) -> None:
        self.assertEqual(IntentClass.LOOKUP.value, "LOOKUP")
        self.assertEqual(IntentClass.QUERY.value, "QUERY")
        self.assertEqual(IntentClass.INGEST.value, "INGEST")
        self.assertEqual(IntentClass.REVISE.value, "REVISE")
        self.assertEqual(IntentClass.WILDCARD.value, "*")

    def test_predicate_operator_values(self) -> None:
        self.assertEqual(PredicateOperator.EQ.value, "EQ")
        self.assertEqual(PredicateOperator.NEQ.value, "NEQ")
        self.assertEqual(PredicateOperator.GT.value, "GT")
        self.assertEqual(PredicateOperator.LT.value, "LT")
        self.assertEqual(PredicateOperator.GTE.value, "GTE")
        self.assertEqual(PredicateOperator.LTE.value, "LTE")
        self.assertEqual(PredicateOperator.CONTAINS.value, "CONTAINS")
        self.assertEqual(PredicateOperator.IN.value, "IN")
        self.assertEqual(PredicateOperator.LIKE.value, "LIKE")
        self.assertEqual(PredicateOperator.ILIKE.value, "ILIKE")
        self.assertEqual(PredicateOperator.SIMILAR.value, "SIMILAR")

    def test_logic_operator_values(self) -> None:
        self.assertEqual(LogicOperator.AND.value, "AND")
        self.assertEqual(LogicOperator.OR.value, "OR")
        self.assertEqual(LogicOperator.NOT.value, "NOT")

    def test_issue_severity_values(self) -> None:
        self.assertEqual(IssueSeverity.BLOCKING.value, "BLOCKING")
        self.assertEqual(IssueSeverity.WARNING.value, "WARNING")

    def test_consistency_level_values(self) -> None:
        self.assertEqual(ConsistencyLevel.STRONG.value, "STRONG")
        self.assertEqual(ConsistencyLevel.EVENTUAL.value, "EVENTUAL")

    def test_field_type_values(self) -> None:
        self.assertEqual(FieldType.STRING.value, "STRING")
        self.assertEqual(FieldType.INTEGER.value, "INTEGER")
        self.assertEqual(FieldType.FLOAT.value, "FLOAT")
        self.assertEqual(FieldType.BOOLEAN.value, "BOOLEAN")
        self.assertEqual(FieldType.DATE.value, "DATE")
        self.assertEqual(FieldType.TIMESTAMP.value, "TIMESTAMP")
        self.assertEqual(FieldType.VECTOR.value, "VECTOR")
        self.assertEqual(FieldType.BLOB.value, "BLOB")
        self.assertEqual(FieldType.JSON.value, "JSON")

    def test_predicate_usage_values(self) -> None:
        self.assertEqual(PredicateUsage.REQUIRED.value, "REQUIRED")
        self.assertEqual(PredicateUsage.OPTIONAL.value, "OPTIONAL")

    def test_validation_issue_code_values(self) -> None:
        self.assertEqual(
            ValidationIssueCode.MISSING_REQUIRED_PREDICATE.value, "MISSING_REQUIRED_PREDICATE"
        )
        self.assertEqual(ValidationIssueCode.INVALID_FORMAT.value, "INVALID_FORMAT")
        self.assertEqual(ValidationIssueCode.FIELD_NOT_PERMITTED.value, "FIELD_NOT_PERMITTED")
        self.assertEqual(ValidationIssueCode.FIELD_NOT_FOUND.value, "FIELD_NOT_FOUND")
        self.assertEqual(ValidationIssueCode.INVALID_OPERATOR.value, "INVALID_OPERATOR")
        self.assertEqual(ValidationIssueCode.INVALID_VALUE.value, "INVALID_VALUE")
        self.assertEqual(ValidationIssueCode.CARDINALITY_EXCEEDED.value, "CARDINALITY_EXCEEDED")


class TestJSONRPCTypes(unittest.TestCase):
    """Tests for JSON-RPC types."""

    def test_jsonrpc_error(self) -> None:
        error = JSONRPCError(code=-32600, message="Invalid request")
        self.assertEqual(error.code, -32600)
        self.assertEqual(error.message, "Invalid request")
        self.assertIsNone(error.data)

    def test_jsonrpc_error_with_data(self) -> None:
        error = JSONRPCError(code=-32602, message="Invalid params", data={"field": "missing"})
        self.assertEqual(error.code, -32602)
        self.assertEqual(error.data, {"field": "missing"})

    def test_jsonrpc_request(self) -> None:
        request = JSONRPCRequest(id=1, method="adp.ping")
        self.assertEqual(request.jsonrpc, "2.0")
        self.assertEqual(request.id, 1)
        self.assertEqual(request.method, "adp.ping")
        self.assertIsNone(request.params)

    def test_jsonrpc_request_with_params(self) -> None:
        request = JSONRPCRequest(id="req-123", method="adp.discover", params={"cursor": "abc"})
        self.assertEqual(request.id, "req-123")
        self.assertEqual(request.params, {"cursor": "abc"})

    def test_jsonrpc_result_response(self) -> None:
        response = JSONRPCResultResponse(id=1, result={"valid": True})
        self.assertEqual(response.jsonrpc, "2.0")
        self.assertEqual(response.id, 1)
        self.assertEqual(response.result, {"valid": True})

    def test_jsonrpc_error_response(self) -> None:
        error = JSONRPCError(code=-32600, message="Invalid request")
        response = JSONRPCErrorResponse(error=error)
        self.assertEqual(response.jsonrpc, "2.0")
        self.assertIsNone(response.id)
        self.assertEqual(response.error.code, -32600)

    def test_request_params_with_meta(self) -> None:
        params = RequestParams.model_validate({"_meta": {"progressToken": "token-123"}})
        self.assertEqual(params.meta_, {"progressToken": "token-123"})

    def test_result_extra_fields(self) -> None:
        result = Result.model_validate({"custom_field": "value"})
        self.assertEqual(result.custom_field, "value")  # type: ignore[attr-defined]


class TestPredicateTypes(unittest.TestCase):
    """Tests for predicate types."""

    def test_similar_value(self) -> None:
        similar = SimilarValue(vector=[0.1, 0.2, 0.3], top=10, threshold=0.8)
        self.assertEqual(similar.vector, [0.1, 0.2, 0.3])
        self.assertEqual(similar.top, 10)
        self.assertEqual(similar.threshold, 0.8)

    def test_similar_value_with_distance_function(self) -> None:
        similar = SimilarValue.model_validate({"vector": [0.1, 0.2], "distanceFunction": "COSINE"})
        self.assertEqual(similar.distance_function, "COSINE")

    def test_similar_value_text_not_yet_supported(self) -> None:
        with self.assertRaisesRegex(ValidationError, "not yet supported"):
            SimilarValue(text="hello world", top=5)

    def test_similar_value_text_and_vector_mutually_exclusive(self) -> None:
        with self.assertRaisesRegex(ValidationError, "mutually exclusive"):
            SimilarValue(text="hello", vector=[0.1], top=5)

    def test_similar_value_neither_text_nor_vector_is_allowed(self) -> None:
        sv = SimilarValue(top=5)
        self.assertIsNone(sv.text)
        self.assertIsNone(sv.vector)

    def test_predicate(self) -> None:
        pred = Predicate.model_validate({"fieldId": "name", "op": "EQ", "value": "John"})
        self.assertEqual(pred.field_id, "name")
        self.assertEqual(pred.op, PredicateOperator.EQ)
        self.assertEqual(pred.value, "John")

    def test_predicate_with_list_value(self) -> None:
        pred = Predicate.model_validate({"fieldId": "status", "op": "IN", "value": ["A", "B", "C"]})
        self.assertEqual(pred.op, PredicateOperator.IN)
        self.assertEqual(pred.value, ["A", "B", "C"])

    def test_identity_predicate(self) -> None:
        pred = IdentityPredicate.model_validate({"fieldId": "id", "op": "EQ", "value": 123})
        self.assertEqual(pred.field_id, "id")
        self.assertEqual(pred.op, "EQ")
        self.assertEqual(pred.value, 123)

    def test_identity_predicate_requires_eq(self) -> None:
        with self.assertRaises(ValidationError):
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
        self.assertEqual(group.op, LogicOperator.AND)
        self.assertEqual(len(group.predicates), 2)

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
        self.assertEqual(group.op, LogicOperator.OR)
        self.assertEqual(len(group.predicates), 2)
        self.assertIsInstance(group.predicates[0], PredicateGroup)


class TestInitializeTypes(unittest.TestCase):
    """Tests for initialize types."""

    def test_implementation(self) -> None:
        impl = Implementation(name="ADP-Hypervisor", version="0.1.0")
        self.assertEqual(impl.name, "ADP-Hypervisor")
        self.assertEqual(impl.version, "0.1.0")

    def test_client_capabilities(self) -> None:
        caps = ClientCapabilities()
        self.assertIsNone(caps.experimental)

    def test_client_capabilities_with_experimental(self) -> None:
        caps = ClientCapabilities(experimental={"feature1": {"enabled": True}})
        self.assertEqual(caps.experimental, {"feature1": {"enabled": True}})

    def test_server_capabilities(self) -> None:
        caps = ServerCapabilities.model_validate(
            {
                "supportedIntentClasses": ["QUERY", "LOOKUP"],
            }
        )
        self.assertEqual(caps.supported_intent_classes, [IntentClass.QUERY, IntentClass.LOOKUP])

    def test_initialize_request_params(self) -> None:
        params = InitializeRequestParams.model_validate(
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"},
            }
        )
        self.assertEqual(params.protocol_version, "2026-01-20")
        self.assertEqual(params.client_info.name, "TestClient")

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
        self.assertEqual(request.method, "adp.initialize")
        self.assertEqual(request.params.protocol_version, "2026-01-20")

    def test_initialize_result(self) -> None:
        result = InitializeResult.model_validate(
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {"supportedIntentClasses": ["*"]},
                "serverInfo": {"name": "ADP-Hypervisor", "version": "0.1.0"},
                "instructions": "Use discover to find resources",
            }
        )
        self.assertEqual(result.protocol_version, "2026-01-20")
        self.assertEqual(result.server_info.name, "ADP-Hypervisor")
        self.assertEqual(result.instructions, "Use discover to find resources")


class TestPingTypes(unittest.TestCase):
    """Tests for ping types."""

    def test_ping_request(self) -> None:
        request = PingRequest(id=1)
        self.assertEqual(request.method, "adp.ping")
        self.assertIsNone(request.params)


class TestPaginationTypes(unittest.TestCase):
    """Tests for pagination types."""

    def test_paginated_request_params(self) -> None:
        params = PaginatedRequestParams(cursor="abc123")
        self.assertEqual(params.cursor, "abc123")

    def test_paginated_result(self) -> None:
        result = PaginatedResult.model_validate({"nextCursor": "next-page"})
        self.assertEqual(result.next_cursor, "next-page")


class TestDiscoverTypes(unittest.TestCase):
    """Tests for discover types."""

    def test_discover_filter(self) -> None:
        filter_ = DiscoverFilter.model_validate(
            {
                "domainPrefix": "com.acme",
                "intentClass": "QUERY",
                "keyword": "finance",
            }
        )
        self.assertEqual(filter_.domain_prefix, "com.acme")
        self.assertEqual(filter_.intent_class, IntentClass.QUERY)
        self.assertEqual(filter_.keyword, "finance")

    def test_discover_request_params(self) -> None:
        params = DiscoverRequestParams.model_validate(
            {
                "filter": {"domainPrefix": "com.acme"},
                "cursor": "page2",
            }
        )
        self.assertIsNotNone(params.filter)
        self.assertIsNotNone(params.filter)
        self.assertEqual(params.filter.domain_prefix, "com.acme")
        self.assertEqual(params.cursor, "page2")

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
        self.assertEqual(resource.resource_id, "com.acme.finance:bank_failures")
        self.assertEqual(resource.version, 1)
        self.assertEqual(resource.intent_classes, [IntentClass.QUERY, IntentClass.LOOKUP])
        self.assertEqual(resource.tags, ["PII-FREE", "FINANCE"])

    def test_discover_result(self) -> None:
        result = DiscoverResult.model_validate(
            {
                "resources": [
                    {
                        "resourceId": "res1",
                        "version": 1,
                        "intentClasses": ["QUERY"],
                        "description": "Resource 1",
                    },
                    {
                        "resourceId": "res2",
                        "version": 2,
                        "intentClasses": ["LOOKUP"],
                        "description": "Resource 2",
                    },
                ],
                "nextCursor": "page2",
            }
        )
        self.assertEqual(len(result.resources), 2)
        self.assertEqual(result.next_cursor, "page2")


class TestDescribeTypes(unittest.TestCase):
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
        self.assertEqual(metadata.cardinality, 1000)
        self.assertEqual(metadata.format, "YYYY-MM-DD")
        self.assertTrue(metadata.whitelist_only)
        self.assertEqual(metadata.hint, "Use ISO format")

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
        self.assertEqual(field.field_id, "name")
        self.assertEqual(field.type, FieldType.STRING)
        self.assertEqual(field.samples, ["John", "Jane"])
        self.assertFalse(field.is_masked)
        self.assertTrue(field.is_searchable)

    def test_field_without_type_is_allowed(self) -> None:
        """Field.type is optional; when omitted it should not appear in dumps."""
        field = Field.model_validate({"fieldId": "payload"})
        self.assertEqual(field.field_id, "payload")
        self.assertIsNone(field.type)

        # By default, dumps should include type=None (since it is part of the model).
        dumped = field.model_dump(by_alias=True)
        self.assertIn("type", dumped)
        self.assertIsNone(dumped["type"])

        # When exclude_none is used, the type field should be omitted entirely.
        dumped_excluding_none = field.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(dumped_excluding_none, {"fieldId": "payload"})

    def test_predicate_capability(self) -> None:
        cap = PredicateCapability.model_validate(
            {
                "fieldId": "status",
                "usage": "REQUIRED",
                "operators": ["EQ", "IN"],
            }
        )
        self.assertEqual(cap.field_id, "status")
        self.assertEqual(cap.usage, PredicateUsage.REQUIRED)
        self.assertEqual(cap.operators, [PredicateOperator.EQ, PredicateOperator.IN])

    def test_projection_capability(self) -> None:
        cap = ProjectionCapability.model_validate({"fieldId": "name"})
        self.assertEqual(cap.field_id, "name")

    def test_mutable_capability(self) -> None:
        cap = MutableCapability.model_validate(
            {
                "fieldId": "status",
                "constraints": {"maxLength": 100},
            }
        )
        self.assertEqual(cap.field_id, "status")
        self.assertEqual(cap.constraints, {"maxLength": 100})

    def test_capabilities(self) -> None:
        caps = Capabilities.model_validate(
            {
                "predicates": [{"fieldId": "id", "usage": "REQUIRED", "operators": ["EQ"]}],
                "projections": [{"fieldId": "name"}],
            }
        )
        self.assertEqual(len(caps.predicates or []), 1)
        self.assertEqual(len(caps.projections or []), 1)

    def test_usage_contract(self) -> None:
        contract = UsageContract.model_validate(
            {
                "fields": [{"fieldId": "id", "type": "INTEGER"}],
                "capabilities": {
                    "predicates": [{"fieldId": "id", "usage": "OPTIONAL", "operators": ["EQ"]}],
                },
            }
        )
        self.assertEqual(len(contract.fields), 1)
        self.assertIsNotNone(contract.capabilities.predicates)

    def test_describe_request_params(self) -> None:
        params = DescribeRequestParams.model_validate(
            {
                "resourceId": "com.acme:users",
                "intentClass": "QUERY",
                "version": 2,
            }
        )
        self.assertEqual(params.resource_id, "com.acme:users")
        self.assertEqual(params.intent_class, IntentClass.QUERY)
        self.assertEqual(params.version, 2)

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
        self.assertEqual(result.resource_id, "com.acme:users")
        self.assertEqual(result.version, 1)
        self.assertEqual(result.intent_class, IntentClass.QUERY)


class TestIntentTypes(unittest.TestCase):
    """Tests for intent types."""

    def test_lookup_intent(self) -> None:
        intent = LookupIntent.model_validate(
            {
                "intentClass": "LOOKUP",
                "resourceId": "com.acme:users",
                "key": {"fieldId": "id", "op": "EQ", "value": 123},
                "projections": ["name", "email"],
            }
        )
        self.assertEqual(intent.intent_class, "LOOKUP")
        self.assertEqual(intent.resource_id, "com.acme:users")
        self.assertEqual(intent.key.field_id, "id")
        self.assertEqual(intent.projections, ["name", "email"])

    def test_sort_order(self) -> None:
        order = SortOrder.model_validate({"direction": "ASC", "fieldId": "name"})
        self.assertEqual(order.direction, "ASC")
        self.assertEqual(order.field_id, "name")

    def test_query_intent(self) -> None:
        intent = QueryIntent.model_validate(
            {
                "intentClass": "QUERY",
                "resourceId": "com.acme:orders",
                "predicates": {
                    "op": "AND",
                    "predicates": [{"fieldId": "status", "op": "EQ", "value": "active"}],
                },
                "projections": ["id", "name"],
                "orderBy": [{"direction": "DESC", "fieldId": "created_at"}],
                "limit": 100,
            }
        )
        self.assertEqual(intent.intent_class, "QUERY")
        self.assertEqual(intent.resource_id, "com.acme:orders")
        self.assertEqual(intent.predicates.op, LogicOperator.AND)
        self.assertEqual(intent.limit, 100)

    def test_ingest_intent(self) -> None:
        intent = IngestIntent.model_validate(
            {
                "intentClass": "INGEST",
                "resourceId": "com.acme:users",
                "payload": [
                    {"name": "John", "age": 30},
                    {"name": "Jane", "age": 25},
                ],
            }
        )
        self.assertEqual(intent.intent_class, "INGEST")
        self.assertEqual(intent.resource_id, "com.acme:users")
        self.assertEqual(len(intent.payload), 2)

    def test_revise_intent(self) -> None:
        intent = ReviseIntent.model_validate(
            {
                "intentClass": "REVISE",
                "resourceId": "com.acme:users",
                "predicates": {
                    "op": "AND",
                    "predicates": [{"fieldId": "id", "op": "EQ", "value": 123}],
                },
                "payload": {"status": "inactive"},
            }
        )
        self.assertEqual(intent.intent_class, "REVISE")
        self.assertEqual(intent.resource_id, "com.acme:users")
        self.assertEqual(intent.payload, {"status": "inactive"})


class TestValidateTypes(unittest.TestCase):
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
        self.assertEqual(issue.code, ValidationIssueCode.FIELD_NOT_FOUND)
        self.assertEqual(issue.severity, IssueSeverity.BLOCKING)
        self.assertEqual(issue.correction_hint, "Check available fields with describe")

    def test_validate_request_params(self) -> None:
        params = ValidateRequestParams.model_validate(
            {
                "intent": {
                    "intentClass": "LOOKUP",
                    "resourceId": "com.acme:users",
                    "key": {"fieldId": "id", "op": "EQ", "value": 1},
                },
            }
        )
        self.assertIsInstance(params.intent, LookupIntent)
        self.assertEqual(params.intent.resource_id, "com.acme:users")

    def test_validate_result_valid(self) -> None:
        result = ValidateResult.model_validate({"valid": True})
        self.assertTrue(result.valid)
        self.assertIsNone(result.issues)

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
        self.assertFalse(result.valid)
        self.assertEqual(len(result.issues or []), 1)


class TestExecuteTypes(unittest.TestCase):
    """Tests for execute types."""

    def test_execute_request_params(self) -> None:
        params = ExecuteRequestParams.model_validate(
            {
                "intent": {
                    "intentClass": "QUERY",
                    "resourceId": "com.acme:users",
                    "predicates": {
                        "op": "AND",
                        "predicates": [{"fieldId": "status", "op": "EQ", "value": "active"}],
                    },
                },
                "cursor": "page2",
            }
        )
        self.assertIsInstance(params.intent, QueryIntent)
        self.assertEqual(params.intent.resource_id, "com.acme:users")

    def test_execution_metadata(self) -> None:
        metadata = ExecutionMetadata.model_validate(
            {
                "durationMs": 150,
                "sourceSystem": "PostgreSQL",
                "consistency": "STRONG",
            }
        )
        self.assertEqual(metadata.duration_ms, 150)
        self.assertEqual(metadata.source_system, "PostgreSQL")
        self.assertEqual(metadata.consistency, ConsistencyLevel.STRONG)

    def test_execute_result(self) -> None:
        result = ExecuteResult.model_validate(
            {
                "results": [{"id": 1, "name": "John"}, {"id": 2, "name": "Jane"}],
                "executionMetadata": {"durationMs": 100},
                "nextCursor": "page2",
            }
        )
        self.assertEqual(len(result.results), 2)
        self.assertIsNotNone(result.execution_metadata)
        self.assertIsNotNone(result.execution_metadata)
        self.assertEqual(result.execution_metadata.duration_ms, 100)
        self.assertEqual(result.next_cursor, "page2")


class TestErrorCodes(unittest.TestCase):
    """Tests for error code constants."""

    def test_standard_error_codes(self) -> None:
        self.assertEqual(PARSE_ERROR, -32700)
        self.assertEqual(INVALID_REQUEST, -32600)
        self.assertEqual(METHOD_NOT_FOUND, -32601)
        self.assertEqual(INVALID_PARAMS, -32602)
        self.assertEqual(INTERNAL_ERROR, -32603)

    def test_adp_error_codes(self) -> None:
        self.assertEqual(RESOURCE_NOT_FOUND, -32001)
        self.assertEqual(VALIDATION_FAILED, -32002)
        self.assertEqual(UNAUTHORIZED, -32003)
        self.assertEqual(EXECUTION_FAILED, -32004)


class TestADPErrors(unittest.TestCase):
    """Tests for ADP error classes."""

    def test_adp_error_base(self) -> None:
        error = ADPError("Something went wrong")
        self.assertEqual(str(error), "Something went wrong")
        self.assertEqual(error.code, INTERNAL_ERROR)

    def test_adp_error_to_dict(self) -> None:
        error = ADPError("Error message", data={"detail": "info"})
        error_dict = error.to_dict()
        self.assertEqual(error_dict["code"], INTERNAL_ERROR)
        self.assertEqual(error_dict["message"], "Error message")
        self.assertEqual(error_dict["data"], {"detail": "info"})

    def test_parse_error(self) -> None:
        error = ParseError()
        self.assertEqual(error.code, PARSE_ERROR)
        self.assertEqual(str(error), "Parse error")

    def test_parse_error_custom_message(self) -> None:
        error = ParseError("Invalid JSON at position 5")
        self.assertEqual(str(error), "Invalid JSON at position 5")

    def test_invalid_request_error(self) -> None:
        error = InvalidRequestError()
        self.assertEqual(error.code, INVALID_REQUEST)

    def test_method_not_found_error(self) -> None:
        error = MethodNotFoundError("Method 'unknown' not found")
        self.assertEqual(error.code, METHOD_NOT_FOUND)
        self.assertEqual(str(error), "Method 'unknown' not found")

    def test_invalid_params_error(self) -> None:
        error = InvalidParamsError(data={"missing": ["resourceId"]})
        self.assertEqual(error.code, INVALID_PARAMS)
        self.assertEqual(error.data, {"missing": ["resourceId"]})

    def test_internal_error(self) -> None:
        error = InternalError()
        self.assertEqual(error.code, INTERNAL_ERROR)

    def test_resource_not_found_error(self) -> None:
        error = ResourceNotFoundError("Resource 'com.acme:unknown' not found")
        self.assertEqual(error.code, RESOURCE_NOT_FOUND)

    def test_validation_failed_error(self) -> None:
        error = ValidationFailedError(data={"issues": [{"code": "FIELD_NOT_FOUND"}]})
        self.assertEqual(error.code, VALIDATION_FAILED)

    def test_unauthorized_error(self) -> None:
        error = UnauthorizedError()
        self.assertEqual(error.code, UNAUTHORIZED)

    def test_execution_failed_error(self) -> None:
        error = ExecutionFailedError("Query timeout")
        self.assertEqual(error.code, EXECUTION_FAILED)
        self.assertEqual(str(error), "Query timeout")


class TestErrorFromCode(unittest.TestCase):
    """Tests for error_from_code function."""

    def test_known_error_codes(self) -> None:
        self.assertIsInstance(error_from_code(PARSE_ERROR), ParseError)
        self.assertIsInstance(error_from_code(INVALID_REQUEST), InvalidRequestError)
        self.assertIsInstance(error_from_code(METHOD_NOT_FOUND), MethodNotFoundError)
        self.assertIsInstance(error_from_code(INVALID_PARAMS), InvalidParamsError)
        self.assertIsInstance(error_from_code(INTERNAL_ERROR), InternalError)
        self.assertIsInstance(error_from_code(RESOURCE_NOT_FOUND), ResourceNotFoundError)
        self.assertIsInstance(error_from_code(VALIDATION_FAILED), ValidationFailedError)
        self.assertIsInstance(error_from_code(UNAUTHORIZED), UnauthorizedError)
        self.assertIsInstance(error_from_code(EXECUTION_FAILED), ExecutionFailedError)

    def test_unknown_error_code(self) -> None:
        error = error_from_code(-32099, "Custom error")
        self.assertIsInstance(error, ADPError)
        self.assertEqual(error.code, -32099)
        self.assertEqual(str(error), "Custom error")

    def test_error_from_code_with_data(self) -> None:
        error = error_from_code(INVALID_PARAMS, "Missing field", data={"field": "name"})
        self.assertEqual(error.data, {"field": "name"})


class TestModelSerialization(unittest.TestCase):
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
        self.assertEqual(data["protocolVersion"], "2026-01-20")
        self.assertEqual(data["serverInfo"]["name"], "ADP-Hypervisor")
        self.assertIn("supportedIntentClasses", data["capabilities"])

    def test_predicate_serialization(self) -> None:
        pred = Predicate.model_validate({"fieldId": "name", "op": "EQ", "value": "John"})
        data = pred.model_dump(by_alias=True)
        self.assertEqual(data["fieldId"], "name")
        self.assertEqual(data["op"], "EQ")

    def test_discover_result_serialization(self) -> None:
        result = DiscoverResult.model_validate(
            {
                "resources": [
                    {
                        "resourceId": "com.acme:users",
                        "version": 1,
                        "intentClasses": ["QUERY"],
                    },
                ],
                "nextCursor": "page2",
            }
        )
        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"][0]["resourceId"], "com.acme:users")
        self.assertEqual(data["nextCursor"], "page2")


# =============================================================================
# PredicateExpression / normalize_to_predicate_group Tests
# =============================================================================


class TestPredicateExpression(unittest.TestCase):
    """Tests for PredicateExpression type and normalize_to_predicate_group."""

    def test_query_intent_accepts_bare_predicate(self) -> None:
        intent = QueryIntent.model_validate(
            {
                "intentClass": "QUERY",
                "resourceId": "com.acme:test",
                "predicates": {"fieldId": "name", "op": "EQ", "value": "Alice"},
            }
        )
        self.assertIsInstance(intent.predicates, Predicate)

    def test_query_intent_accepts_predicate_group(self) -> None:
        intent = QueryIntent.model_validate(
            {
                "intentClass": "QUERY",
                "resourceId": "com.acme:test",
                "predicates": {
                    "op": "AND",
                    "predicates": [{"fieldId": "name", "op": "EQ", "value": "Alice"}],
                },
            }
        )
        self.assertIsInstance(intent.predicates, PredicateGroup)

    def test_revise_intent_accepts_bare_predicate(self) -> None:
        intent = ReviseIntent.model_validate(
            {
                "intentClass": "REVISE",
                "resourceId": "com.acme:test",
                "predicates": {"fieldId": "id", "op": "EQ", "value": "123"},
                "payload": {"name": "updated"},
            }
        )
        self.assertIsInstance(intent.predicates, Predicate)

    def test_normalize_bare_predicate(self) -> None:
        pred = Predicate(field_id="a", op=PredicateOperator.EQ, value="1")
        group = normalize_to_predicate_group(pred)
        self.assertIsInstance(group, PredicateGroup)
        self.assertEqual(group.op, LogicOperator.AND)
        self.assertEqual(len(group.predicates), 1)
        self.assertEqual(group.predicates[0], pred)

    def test_normalize_predicate_group_passthrough(self) -> None:
        group = PredicateGroup(
            op=LogicOperator.OR,
            predicates=[
                Predicate(field_id="a", op=PredicateOperator.EQ, value="1"),
            ],
        )
        result = normalize_to_predicate_group(group)
        self.assertIs(result, group)
