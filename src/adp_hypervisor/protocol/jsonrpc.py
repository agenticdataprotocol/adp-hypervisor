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
JSON-RPC 2.0 Types.

This module defines the core JSON-RPC 2.0 types using standard Pydantic BaseModels.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Constants
# =============================================================================

JSONRPC_VERSION = "2.0"


# =============================================================================
# JSON-RPC Types
# =============================================================================


class JSONRPCError(BaseModel):
    """JSON-RPC error object."""

    code: int = Field(..., description="The error type that occurred")
    message: str = Field(
        ..., description="A short description of the error, limited to a concise single sentence"
    )
    data: Any = Field(default=None, description="Additional information about the error")


class RequestParams(BaseModel):
    """Common params for any request."""

    model_config = ConfigDict(extra="allow")

    meta_: dict[str, Any] | None = Field(
        default=None,
        alias="_meta",
        description="Metadata including progress token and other info",
    )


class Result(BaseModel):
    """Common result type for all successful responses."""

    model_config = ConfigDict(extra="allow")

    meta_: dict[str, Any] | None = Field(
        default=None,
        alias="_meta",
        description="Result metadata",
    )


# Common Type Aliases for JSON-RPC
RequestId = Annotated[int, Field(strict=True)] | str
"""A uniquely identifying ID for a request in JSON-RPC."""


class JSONRPCRequest(BaseModel):
    """A JSON-RPC request that expects a response."""

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="JSON-RPC version")
    id: RequestId = Field(..., description="Request ID")
    method: str = Field(..., description="Method name")
    params: dict[str, Any] | None = Field(default=None, description="Request parameters")


class JSONRPCResultResponse(BaseModel):
    """A successful (non-error) response to a request."""

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="JSON-RPC version")
    id: RequestId = Field(..., description="Request ID")
    result: dict[str, Any] = Field(..., description="Result data")


class JSONRPCErrorResponse(BaseModel):
    """A response to a request that indicates an error occurred."""

    jsonrpc: Literal["2.0"] = Field(default="2.0", description="JSON-RPC version")
    id: RequestId | None = Field(default=None, description="Request ID (may be null on errors)")
    error: JSONRPCError = Field(..., description="Error details")


JSONRPCResponse = JSONRPCResultResponse | JSONRPCErrorResponse
"""A response to a request, containing either the result or error."""

JSONRPCMessage = JSONRPCRequest | JSONRPCResponse
"""Any valid JSON-RPC object that can be decoded off the wire, or encoded to be sent."""
