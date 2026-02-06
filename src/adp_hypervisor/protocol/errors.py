"""
ADP Protocol Error Classes.

This module defines JSON-RPC error codes and exception classes for the ADP protocol.
"""

from typing import Any

# =============================================================================
# JSON-RPC Standard Error Codes
# =============================================================================

PARSE_ERROR = -32700
"""Invalid JSON was received by the server."""

INVALID_REQUEST = -32600
"""The JSON sent is not a valid Request object."""

METHOD_NOT_FOUND = -32601
"""The method does not exist / is not available."""

INVALID_PARAMS = -32602
"""Invalid method parameter(s)."""

INTERNAL_ERROR = -32603
"""Internal JSON-RPC error."""

# =============================================================================
# ADP-specific Error Codes (range -32000 to -32099)
# =============================================================================

RESOURCE_NOT_FOUND = -32001
"""The requested resource was not found."""

VALIDATION_FAILED = -32002
"""Intent validation failed."""

UNAUTHORIZED = -32003
"""The client is not authorized to perform the operation."""

EXECUTION_FAILED = -32004
"""Intent execution failed."""


class ADPError(Exception):
    """Base class for all ADP protocol errors."""

    # Default values for subclasses
    _default_code: int = INTERNAL_ERROR
    _default_message: str = "Internal error"

    def __init__(
        self,
        message: str | None = None,
        data: Any = None,
    ) -> None:
        """
        Initialize an ADP error.

        Args:
            message: Optional error message. If not provided, uses the default.
            data: Optional additional error data.
        """
        self._code = self._default_code
        self._message = message if message is not None else self._default_message
        self._data = data
        super().__init__(self._message)

    @property
    def code(self) -> int:
        """Return the error code."""
        return self._code

    @property
    def message(self) -> str:
        """Return the error message."""
        return self._message

    @property
    def data(self) -> Any:
        """Return additional error data."""
        return self._data

    def to_dict(self) -> dict[str, Any]:
        """Convert the error to a JSON-RPC error object."""
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result

    def __str__(self) -> str:
        return self.message


class ParseError(ADPError):
    """Invalid JSON was received by the server."""

    _default_code = PARSE_ERROR
    _default_message = "Parse error"


class InvalidRequestError(ADPError):
    """The JSON sent is not a valid Request object."""

    _default_code = INVALID_REQUEST
    _default_message = "Invalid request"


class MethodNotFoundError(ADPError):
    """The method does not exist / is not available."""

    _default_code = METHOD_NOT_FOUND
    _default_message = "Method not found"


class InvalidParamsError(ADPError):
    """Invalid method parameter(s)."""

    _default_code = INVALID_PARAMS
    _default_message = "Invalid params"


class InternalError(ADPError):
    """Internal JSON-RPC error."""

    _default_code = INTERNAL_ERROR
    _default_message = "Internal error"


class ResourceNotFoundError(ADPError):
    """The requested resource was not found."""

    _default_code = RESOURCE_NOT_FOUND
    _default_message = "Resource not found"


class ValidationFailedError(ADPError):
    """Intent validation failed."""

    _default_code = VALIDATION_FAILED
    _default_message = "Validation failed"


class UnauthorizedError(ADPError):
    """The client is not authorized to perform the operation."""

    _default_code = UNAUTHORIZED
    _default_message = "Unauthorized"


class ExecutionFailedError(ADPError):
    """Intent execution failed."""

    _default_code = EXECUTION_FAILED
    _default_message = "Execution failed"


# Error code to exception class mapping
ERROR_CODE_TO_CLASS: dict[int, type[ADPError]] = {
    PARSE_ERROR: ParseError,
    INVALID_REQUEST: InvalidRequestError,
    METHOD_NOT_FOUND: MethodNotFoundError,
    INVALID_PARAMS: InvalidParamsError,
    INTERNAL_ERROR: InternalError,
    RESOURCE_NOT_FOUND: ResourceNotFoundError,
    VALIDATION_FAILED: ValidationFailedError,
    UNAUTHORIZED: UnauthorizedError,
    EXECUTION_FAILED: ExecutionFailedError,
}


def error_from_code(code: int, message: str | None = None, data: Any = None) -> ADPError:
    """
    Create an appropriate ADPError subclass from an error code.

    Args:
        code: The JSON-RPC error code.
        message: Optional error message.
        data: Optional additional error data.

    Returns:
        An instance of the appropriate ADPError subclass.
    """
    error_class = ERROR_CODE_TO_CLASS.get(code, ADPError)
    error = error_class(message=message, data=data)
    if error_class == ADPError:
        # For unknown error codes, set the code directly
        error._code = code
    return error
