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

"""Tests for the JSON-RPC Dispatcher."""

import json
import unittest
from typing import Any

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


class ValidationParams(BaseModel):
    """A params model that raises Pydantic validation errors."""

    protocol_version: str


class ValidationErrorHandler(Handler):
    """A handler that validates params with Pydantic."""

    @property
    def method(self) -> str:
        return "test.validation"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        ValidationParams.model_validate(params)
        return EmptyResult()


class TestDispatcherRegistration(unittest.TestCase):
    """Tests for handler registration."""

    def test_register_handler(self) -> None:
        dispatcher = Dispatcher()
        handler = MockHandler()

        dispatcher.register_handler(handler)

        self.assertIn("test.method", dispatcher.get_registered_methods())

    def test_register_duplicate_handler_raises(self) -> None:
        dispatcher = Dispatcher()
        handler1 = MockHandler()
        handler2 = MockHandler()

        dispatcher.register_handler(handler1)

        with self.assertRaisesRegex(ValueError, "already registered"):
            dispatcher.register_handler(handler2)

    def test_register_decorator(self) -> None:
        dispatcher = Dispatcher()

        @dispatcher.register("adp.ping")
        async def handle_ping(params: dict[str, Any]) -> EmptyResult:
            return EmptyResult()

        self.assertIn("adp.ping", dispatcher.get_registered_methods())

    def test_register_decorator_duplicate_raises(self) -> None:
        dispatcher = Dispatcher()

        @dispatcher.register("adp.ping")
        async def handle_ping(params: dict[str, Any]) -> EmptyResult:
            return EmptyResult()

        with self.assertRaisesRegex(ValueError, "already registered"):

            @dispatcher.register("adp.ping")
            async def handle_ping_again(params: dict[str, Any]) -> EmptyResult:
                return EmptyResult()

    def test_unregister(self) -> None:
        dispatcher = Dispatcher()
        handler = MockHandler()

        dispatcher.register_handler(handler)
        self.assertIn("test.method", dispatcher.get_registered_methods())

        dispatcher.unregister("test.method")
        self.assertNotIn("test.method", dispatcher.get_registered_methods())

    def test_unregister_nonexistent_does_not_raise(self) -> None:
        dispatcher = Dispatcher()
        # Should not raise
        dispatcher.unregister("nonexistent.method")

    def test_get_registered_methods_empty(self) -> None:
        dispatcher = Dispatcher()
        self.assertEqual(dispatcher.get_registered_methods(), [])

    def test_get_registered_methods_multiple(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(MockHandler("method.one"))
        dispatcher.register_handler(MockHandler("method.two"))

        methods = dispatcher.get_registered_methods()
        self.assertIn("method.one", methods)
        self.assertIn("method.two", methods)
        self.assertEqual(len(methods), 2)


class TestDispatcherDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests for message dispatching."""

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

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["value"], "hello")
        self.assertNotIn("error", response)

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

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertIn("result", response)

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

        self.assertEqual(response["result"]["value"], "default")


class TestDispatcherErrors(unittest.IsolatedAsyncioTestCase):
    """Tests for error handling."""

    async def test_dispatch_parse_error(self) -> None:
        dispatcher = Dispatcher()

        response_str = await dispatcher.dispatch("not valid json{")
        response = json.loads(response_str)

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertIsNone(response["id"])
        self.assertEqual(response["error"]["code"], -32700)  # Parse error
        self.assertIn("Invalid JSON", response["error"]["message"])

    async def test_dispatch_invalid_request(self) -> None:
        dispatcher = Dispatcher()

        # Missing required fields
        request = json.dumps({"jsonrpc": "2.0"})

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        self.assertEqual(response["error"]["code"], -32600)  # Invalid request
        self.assertIsNone(response["id"])
        self.assertEqual(
            response["error"]["message"],
            "Invalid request: `id`: Field required; `method`: Field required.",
        )
        self.assertEqual(
            response["error"]["data"],
            {
                "model": "JSONRPCRequest",
                "validationErrors": [
                    {"path": "id", "message": "Field required", "type": "missing"},
                    {"path": "method", "message": "Field required", "type": "missing"},
                ],
            },
        )
        self.assertNotIn("pydantic.dev", response["error"]["message"])

    async def test_dispatch_invalid_request_reports_per_branch_union_errors(self) -> None:
        """Union fields produce one error per branch with Pydantic's native messages."""
        dispatcher = Dispatcher()

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1.5,
                "method": "test.method",
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        self.assertEqual(response["error"]["code"], -32600)
        # Pydantic emits one error per union branch (id.int and id.str)
        validation_errors = response["error"]["data"]["validationErrors"]
        self.assertEqual(len(validation_errors), 2)
        self.assertEqual(validation_errors[0]["path"], "id.int")
        self.assertEqual(validation_errors[1]["path"], "id.str")
        self.assertNotIn("pydantic.dev", response["error"]["message"])

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

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["error"]["code"], -32601)  # Method not found
        self.assertIn("nonexistent.method", response["error"]["message"])

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

        self.assertEqual(response["error"]["code"], -32602)  # Invalid params

    async def test_dispatch_handler_pydantic_validation_error(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.register_handler(ValidationErrorHandler())

        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.validation",
                "params": {"protocol_version": 123},
            }
        )

        response_str = await dispatcher.dispatch(request)
        response = json.loads(response_str)

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(
            response["error"]["message"],
            "Invalid params: `protocol_version`: Input should be a valid string.",
        )
        self.assertEqual(
            response["error"]["data"],
            {
                "model": "ValidationParams",
                "validationErrors": [
                    {
                        "path": "protocol_version",
                        "message": "Input should be a valid string",
                        "type": "string_type",
                    }
                ],
            },
        )
        self.assertNotIn("pydantic.dev", response["error"]["message"])

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

        self.assertEqual(response["error"]["code"], -32603)  # Internal error

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

        self.assertEqual(response["id"], "my-request-id")

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

        self.assertEqual(response["id"], "string-id-123")


class TestDispatcherUtilities(unittest.TestCase):
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

        self.assertEqual(request.id, 1)
        self.assertEqual(request.method, "test.method")
        self.assertEqual(request.params, {"key": "value"})

    def test_parse_request_invalid_json(self) -> None:
        dispatcher = Dispatcher()

        from adp_hypervisor.protocol import ParseError

        with self.assertRaises(ParseError):
            dispatcher.parse_request("invalid json")

    def test_parse_request_invalid_structure(self) -> None:
        dispatcher = Dispatcher()

        from adp_hypervisor.protocol import InvalidRequestError

        with self.assertRaises(InvalidRequestError):
            dispatcher.parse_request(json.dumps({"not": "valid"}))

    def test_build_response(self) -> None:
        dispatcher = Dispatcher()
        result = MockResult(value="test")

        response = dispatcher.build_response(1, result)

        self.assertEqual(response.id, 1)
        self.assertEqual(response.result, {"value": "test"})

    def test_build_error(self) -> None:
        dispatcher = Dispatcher()
        error = MethodNotFoundError("Method not found: test.method")

        response = dispatcher.build_error(1, error)

        self.assertEqual(response.id, 1)
        self.assertEqual(response.error.code, -32601)
        self.assertIn("test.method", response.error.message)
