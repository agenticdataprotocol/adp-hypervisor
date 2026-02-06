"""Tests for the JSON-RPC Dispatcher."""

import json
from typing import Any

import pytest
from pydantic import BaseModel

from adp_hypervisor.protocol import (
    Dispatcher,
    EmptyResult,
    Handler,
    InvalidParamsError,
    MethodNotFoundError,
)


class MockResult(BaseModel):
    """A mock result for testing."""

    value: str


class MockHandler(Handler):
    """A mock handler for testing."""

    def __init__(self, method_name: str = "test.method") -> None:
        self._method = method_name

    @property
    def method(self) -> str:
        return self._method

    async def handle(self, params: dict[str, Any]) -> MockResult:
        return MockResult(value=params.get("input", "default"))


class ErrorHandler(Handler):
    """A handler that raises errors for testing."""

    @property
    def method(self) -> str:
        return "test.error"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        error_type = params.get("error_type", "generic")
        if error_type == "validation":
            raise InvalidParamsError("Invalid parameter")
        elif error_type == "unexpected":
            raise RuntimeError("Unexpected error")
        return EmptyResult()


class TestDispatcherRegistration:
    """Tests for handler registration."""

    def test_register_handler(self) -> None:
        dispatcher = Dispatcher()
        handler = MockHandler()

        dispatcher.register_handler(handler)

        assert "test.method" in dispatcher.get_registered_methods()

    def test_register_duplicate_handler_raises(self) -> None:
        dispatcher = Dispatcher()
        handler1 = MockHandler()
        handler2 = MockHandler()

        dispatcher.register_handler(handler1)

        with pytest.raises(ValueError, match="already registered"):
            dispatcher.register_handler(handler2)

    def test_register_decorator(self) -> None:
        dispatcher = Dispatcher()

        @dispatcher.register("adp.ping")
        async def handle_ping(params: dict[str, Any]) -> EmptyResult:
            return EmptyResult()

        assert "adp.ping" in dispatcher.get_registered_methods()

    def test_register_decorator_duplicate_raises(self) -> None:
        dispatcher = Dispatcher()

        @dispatcher.register("adp.ping")
        async def handle_ping(params: dict[str, Any]) -> EmptyResult:
            return EmptyResult()

        with pytest.raises(ValueError, match="already registered"):

            @dispatcher.register("adp.ping")
            async def handle_ping_again(params: dict[str, Any]) -> EmptyResult:
                return EmptyResult()

    def test_unregister(self) -> None:
        dispatcher = Dispatcher()
        handler = MockHandler()

        dispatcher.register_handler(handler)
        assert "test.method" in dispatcher.get_registered_methods()

        dispatcher.unregister("test.method")
        assert "test.method" not in dispatcher.get_registered_methods()

    def test_unregister_nonexistent_does_not_raise(self) -> None:
        dispatcher = Dispatcher()
        # Should not raise
        dispatcher.unregister("nonexistent.method")

    def test_get_registered_methods_empty(self) -> None:
        dispatcher = Dispatcher()
        assert dispatcher.get_registered_methods() == []

    def test_get_registered_methods_multiple(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(MockHandler("method.one"))
        dispatcher.register_handler(MockHandler("method.two"))

        methods = dispatcher.get_registered_methods()
        assert "method.one" in methods
        assert "method.two" in methods
        assert len(methods) == 2


class TestDispatcherDispatch:
    """Tests for message dispatching."""

    @pytest.mark.asyncio
    async def test_dispatch_success(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(MockHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.method",
                "params": {"input": "hello"},
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"]["value"] == "hello"
        assert "error" not in response

    @pytest.mark.asyncio
    async def test_dispatch_with_decorator_handler(self) -> None:
        dispatcher = Dispatcher()

        @dispatcher.register("adp.ping")
        async def handle_ping(params: dict[str, Any]) -> EmptyResult:
            return EmptyResult()

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "adp.ping",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response

    @pytest.mark.asyncio
    async def test_dispatch_without_params(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(MockHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.method",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["result"]["value"] == "default"


class TestDispatcherErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_dispatch_parse_error(self) -> None:
        dispatcher = Dispatcher()

        response_str = await dispatcher.dispatch("not valid json{")
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] is None
        assert response["error"]["code"] == -32700  # Parse error
        assert "Invalid JSON" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_dispatch_invalid_request(self) -> None:
        dispatcher = Dispatcher()

        # Missing required fields
        request = json.dumps({"jsonrpc": "2.0"})

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["error"]["code"] == -32600  # Invalid request
        assert response["id"] is None

    @pytest.mark.asyncio
    async def test_dispatch_method_not_found(self) -> None:
        dispatcher = Dispatcher()

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "nonexistent.method",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["error"]["code"] == -32601  # Method not found
        assert "nonexistent.method" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_dispatch_handler_validation_error(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(ErrorHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.error",
                "params": {"error_type": "validation"},
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["error"]["code"] == -32602  # Invalid params

    @pytest.mark.asyncio
    async def test_dispatch_handler_unexpected_error(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(ErrorHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.error",
                "params": {"error_type": "unexpected"},
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["error"]["code"] == -32603  # Internal error

    @pytest.mark.asyncio
    async def test_dispatch_preserves_request_id_on_error(self) -> None:
        dispatcher = Dispatcher()

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "my-request-id",
                "method": "nonexistent.method",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["id"] == "my-request-id"

    @pytest.mark.asyncio
    async def test_dispatch_string_request_id(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(MockHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "string-id-123",
                "method": "test.method",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        assert response["id"] == "string-id-123"


class TestDispatcherUtilities:
    """Tests for utility methods."""

    def test_parse_request_valid(self) -> None:
        dispatcher = Dispatcher()

        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.method",
                "params": {"key": "value"},
            }
        )

        request = dispatcher.parse_request(message)

        assert request.id == 1
        assert request.method == "test.method"
        assert request.params == {"key": "value"}

    def test_parse_request_invalid_json(self) -> None:
        dispatcher = Dispatcher()

        from adp_hypervisor.protocol import ParseError

        with pytest.raises(ParseError):
            dispatcher.parse_request("invalid json")

    def test_parse_request_invalid_structure(self) -> None:
        dispatcher = Dispatcher()

        from adp_hypervisor.protocol import InvalidRequestError

        with pytest.raises(InvalidRequestError):
            dispatcher.parse_request(json.dumps({"not": "valid"}))

    def test_build_response(self) -> None:
        dispatcher = Dispatcher()
        result = MockResult(value="test")

        response = dispatcher.build_response(1, result)

        assert response.id == 1
        assert response.result == {"value": "test"}

    def test_build_error(self) -> None:
        dispatcher = Dispatcher()
        error = MethodNotFoundError("Method not found: test.method")

        response = dispatcher.build_error(1, error)

        assert response.id == 1
        assert response.error.code == -32601
        assert "test.method" in response.error.message
