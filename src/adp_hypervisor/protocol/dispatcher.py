"""
JSON-RPC 2.0 Dispatcher.

This module implements the JSON-RPC dispatcher that handles message parsing,
method routing, and response wrapping for the ADP server.
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from adp_hypervisor.protocol.errors import (
    ADPError,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    ParseError,
)
from adp_hypervisor.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCResultResponse,
    RequestId,
)

logger = logging.getLogger(__name__)

# Type variable for handler result types
TResult = TypeVar("TResult", bound=BaseModel)


class Handler(ABC):
    """Handler abstract base class for processing ADP requests."""

    @property
    @abstractmethod
    def method(self) -> str:
        """Return the method name this handler processes."""

    @abstractmethod
    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process request and return result."""


# Type alias for handler functions
HandlerFunc = Callable[[dict[str, Any]], Any]


class Dispatcher:
    """
    JSON-RPC 2.0 Dispatcher.

    Handles message parsing, method routing, error handling,
    and response serialization for ADP protocol messages.
    """

    def __init__(self) -> None:
        """Initialize the dispatcher with an empty handler registry."""
        self._handlers: dict[str, Handler | HandlerFunc] = {}

    def register_handler(self, handler: Handler) -> None:
        """
        Register a handler instance for a method.

        Args:
            handler: The handler instance to register.

        Raises:
            ValueError: If a handler is already registered for the method.
        """
        method = handler.method
        if method in self._handlers:
            raise ValueError(f"Handler already registered for method: {method}")
        self._handlers[method] = handler
        logger.debug("Registered handler for method: %s", method)

    def register(self, method: str) -> Callable[[HandlerFunc], HandlerFunc]:
        """
        Decorator to register a handler function for a method.

        Args:
            method: The method name to register.

        Returns:
            A decorator that registers the handler function.

        Example:
            @dispatcher.register("adp.ping")
            async def handle_ping(params: dict) -> EmptyResult:
                return EmptyResult()
        """

        def decorator(func: HandlerFunc) -> HandlerFunc:
            if method in self._handlers:
                raise ValueError(f"Handler already registered for method: {method}")
            self._handlers[method] = func
            logger.debug("Registered handler function for method: %s", method)
            return func

        return decorator

    def unregister(self, method: str) -> None:
        """
        Unregister a handler for a method.

        Args:
            method: The method name to unregister.
        """
        if method in self._handlers:
            del self._handlers[method]
            logger.debug("Unregistered handler for method: %s", method)

    def get_registered_methods(self) -> list[str]:
        """
        Get a list of all registered method names.

        Returns:
            A list of registered method names.
        """
        return list(self._handlers.keys())

    async def dispatch(self, message: str) -> str:
        """
        Parse and dispatch a JSON-RPC message.

        Args:
            message: The raw JSON-RPC message string.

        Returns:
            The JSON-RPC response string.
        """
        request_id: RequestId | None = None

        try:
            # Parse JSON
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse JSON: %s", e)
                raise ParseError(f"Invalid JSON: {e}") from e

            # Validate JSON-RPC request structure
            try:
                request = JSONRPCRequest.model_validate(data)
                request_id = request.id
            except ValidationError as e:
                logger.warning("Invalid JSON-RPC request: %s", e)
                raise InvalidRequestError(f"Invalid request: {e}") from e

            # Route to handler
            result = await self._route(request)

            # Build success response
            response: JSONRPCResultResponse | JSONRPCErrorResponse = JSONRPCResultResponse(
                id=request_id,
                result=result.model_dump(by_alias=True, exclude_none=True),
            )

        except ADPError as e:
            logger.warning("ADP error: [%d] %s", e.code, e.message)
            response = self._build_error_response(request_id, e)

        except Exception as e:
            logger.exception("Unexpected error during dispatch")
            error = InternalError(str(e))
            response = self._build_error_response(request_id, error)

        # For error responses, id must be present (even if null) per JSON-RPC 2.0 spec
        if isinstance(response, JSONRPCErrorResponse):
            return response.model_dump_json(by_alias=True)
        return response.model_dump_json(by_alias=True, exclude_none=True)

    def parse_request(self, message: str) -> JSONRPCRequest:
        """
        Parse a JSON-RPC request message.

        This is a utility method for parsing requests without dispatching.

        Args:
            message: The raw JSON-RPC message string.

        Returns:
            The parsed JSON-RPC request.

        Raises:
            ParseError: If the message is not valid JSON.
            InvalidRequestError: If the message is not a valid JSON-RPC request.
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON: {e}") from e

        try:
            return JSONRPCRequest.model_validate(data)
        except ValidationError as e:
            raise InvalidRequestError(f"Invalid request: {e}") from e

    def build_response(self, request_id: RequestId, result: BaseModel) -> JSONRPCResultResponse:
        """
        Build a JSON-RPC success response.

        This is a utility method for building responses manually.

        Args:
            request_id: The request ID.
            result: The result model.

        Returns:
            A JSON-RPC success response.
        """
        return JSONRPCResultResponse(
            id=request_id,
            result=result.model_dump(by_alias=True, exclude_none=True),
        )

    def build_error(self, request_id: RequestId | None, error: ADPError) -> JSONRPCErrorResponse:
        """
        Build a JSON-RPC error response.

        This is a utility method for building error responses manually.

        Args:
            request_id: The request ID (may be None).
            error: The ADP error.

        Returns:
            A JSON-RPC error response.
        """
        return self._build_error_response(request_id, error)

    async def _route(self, request: JSONRPCRequest) -> BaseModel:
        """
        Route a request to the appropriate handler.

        Args:
            request: The parsed JSON-RPC request.

        Returns:
            The handler result.

        Raises:
            MethodNotFoundError: If no handler is registered for the method.
            InvalidParamsError: If the parameters are invalid.
        """
        method = request.method
        handler = self._handlers.get(method)

        if handler is None:
            raise MethodNotFoundError(f"Method not found: {method}")

        params = request.params or {}

        try:
            if isinstance(handler, Handler):
                result = await handler.handle(params)
            else:
                # Handler is a function
                result = await handler(params)
        except ADPError:
            # Re-raise ADP errors as-is
            raise
        except ValidationError as e:
            # Convert Pydantic validation errors to InvalidParamsError
            raise InvalidParamsError(str(e)) from e
        except Exception as e:
            # Wrap unexpected errors
            logger.exception("Handler error for method %s", method)
            raise InternalError(f"Handler error: {e}") from e

        return result

    def _build_error_response(
        self, request_id: RequestId | None, error: ADPError
    ) -> JSONRPCErrorResponse:
        """
        Build a JSON-RPC error response.

        Args:
            request_id: The request ID (may be None for parse errors).
            error: The ADP error.

        Returns:
            A JSON-RPC error response.
        """
        return JSONRPCErrorResponse(
            id=request_id,
            error=JSONRPCError(
                code=error.code,
                message=error.message,
                data=error.data,
            ),
        )
