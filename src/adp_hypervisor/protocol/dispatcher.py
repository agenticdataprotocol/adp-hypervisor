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
JSON-RPC 2.0 Dispatcher.

This module implements the JSON-RPC dispatcher that handles message parsing,
method routing, and response wrapping for the ADP server.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from adp_hypervisor.handlers.base import Handler
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

# Type alias for handler functions
HandlerFunc = Callable[[dict[str, Any]], Any]

# Maximum number of individual errors shown in the summary message.
_MAX_SUMMARY_ERRORS = 3


def _format_validation_error(
    prefix: str, validation_error: ValidationError
) -> tuple[str, dict[str, Any]]:
    """Convert a Pydantic ValidationError into a JSON-RPC-friendly message and data payload.

    Uses Pydantic's own ``msg`` text as-is (e.g. "Field required",
    "Input should be a valid string") instead of rewriting messages manually.
    This keeps the code simple and automatically benefits from upstream
    improvements in Pydantic's error descriptions.

    Args:
        prefix: A short label for the error context, e.g. "Invalid request".
        validation_error: The Pydantic validation error to format.

    Returns:
        A ``(summary_message, data_dict)`` tuple where *data_dict* contains
        a ``validationErrors`` list suitable for ``error.data`` in a JSON-RPC
        error response.
    """
    raw_errors = validation_error.errors(
        include_url=False, include_input=False, include_context=False
    )
    details = [
        {"path": _format_loc(e["loc"]), "message": e["msg"], "type": e["type"]} for e in raw_errors
    ]
    data: dict[str, Any] = {"validationErrors": details}
    if validation_error.title:
        data["model"] = validation_error.title
    return _build_summary(prefix, details), data


def _format_loc(loc: tuple[Any, ...]) -> str:
    """Format a Pydantic ``loc`` tuple into a human-readable dotted path.

    Pydantic represents field locations as tuples like ``("items", 0, "name")``.
    This converts them into dotted notation: ``"items[0].name"``.
    """
    if not loc:
        return "<root>"
    parts: list[str] = []
    for segment in loc:
        if isinstance(segment, int):
            # Array index — attach to the preceding path segment: "items" → "items[0]"
            if parts:
                parts[-1] = f"{parts[-1]}[{segment}]"
            else:
                parts.append(f"[{segment}]")
        else:
            parts.append(str(segment))
    return ".".join(parts)


def _build_summary(prefix: str, details: list[dict[str, Any]]) -> str:
    """Build a one-line summary from the first few validation errors."""
    if not details:
        return prefix
    snippets: list[str] = []
    for d in details[:_MAX_SUMMARY_ERRORS]:
        path = d["path"]
        snippets.append(d["message"] if path == "<root>" else f"`{path}`: {d['message']}")
    summary = f"{prefix}: {'; '.join(snippets)}."
    remaining = len(details) - _MAX_SUMMARY_ERRORS
    if remaining > 0:
        summary = f"{prefix}: {'; '.join(snippets)}; and {remaining} more."
    return summary


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
        method: str = "<unknown>"
        start_s = time.monotonic()

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
                method = request.method
            except ValidationError as e:
                error_message, error_data = _format_validation_error("Invalid request", e)
                logger.debug("Invalid JSON-RPC request: %s", error_message)
                raise InvalidRequestError(error_message, data=error_data) from e

            logger.debug("Dispatch: method=%s, request_id=%s", method, request_id)

            # Route to handler
            result = await self._route(request)

            duration_ms = int((time.monotonic() - start_s) * 1000)
            logger.debug(
                "Dispatch: method=%s, request_id=%s, status=success, duration_ms=%d",
                method,
                request_id,
                duration_ms,
            )

            # Build success response
            response: JSONRPCResultResponse | JSONRPCErrorResponse = JSONRPCResultResponse(
                id=request_id,
                result=result.model_dump(by_alias=True, exclude_none=True),
            )

        except ADPError as e:
            duration_ms = int((time.monotonic() - start_s) * 1000)
            logger.warning(
                "Dispatch: method=%s, request_id=%s, status=error, code=%d, "
                "message=%s, duration_ms=%d",
                method,
                request_id,
                e.code,
                e.message,
                duration_ms,
            )
            response = self._build_error_response(request_id, e)

        except Exception as e:
            duration_ms = int((time.monotonic() - start_s) * 1000)
            logger.exception(
                "Dispatch: method=%s, request_id=%s, status=unexpected_error, duration_ms=%d",
                method,
                request_id,
                duration_ms,
            )
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
            error_message, error_data = _format_validation_error("Invalid request", e)
            raise InvalidRequestError(error_message, data=error_data) from e

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
            error_message, error_data = _format_validation_error("Invalid params", e)
            raise InvalidParamsError(error_message, data=error_data) from e
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
