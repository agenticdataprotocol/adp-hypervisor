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
HTTP Transport implementation.

This module implements an HTTP transport using Starlette ASGI and uvicorn,
serving JSON-RPC requests via ``POST /adp``.
"""

import json
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from adp_hypervisor.protocol.errors import INTERNAL_ERROR, INVALID_REQUEST
from adp_hypervisor.transport.base import MessageHandler, Transport

logger = logging.getLogger(__name__)


def _jsonrpc_error_body(code: int, message: str) -> str:
    """Build a compact JSON-RPC error response body.

    Args:
        code: JSON-RPC error code.
        message: Human-readable error message.

    Returns:
        A minimal JSON-RPC error response string.
    """
    return json.dumps(
        {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": None},
        separators=(",", ":"),
    )


_ERR_UNSUPPORTED_MEDIA = _jsonrpc_error_body(INVALID_REQUEST, "Unsupported Media Type")
_ERR_EMPTY_BODY = _jsonrpc_error_body(INVALID_REQUEST, "Empty request body")
_ERR_INVALID_ENCODING = _jsonrpc_error_body(INVALID_REQUEST, "Invalid UTF-8 encoding")
_ERR_INTERNAL = _jsonrpc_error_body(INTERNAL_ERROR, "Internal error")


class HttpTransport(Transport):
    """HTTP transport using Starlette ASGI and uvicorn.

    Serves JSON-RPC requests via ``POST /adp`` endpoint.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Initialize the HTTP transport.

        Args:
            host: Network interface to bind to.
            port: TCP port to listen on.
        """
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None

    async def start(self, message_handler: MessageHandler) -> None:
        """Create ASGI app and start uvicorn.

        Blocks until :meth:`stop` is called or the server exits.

        Args:
            message_handler: Async callable that processes a raw JSON-RPC
                message string and returns the response string.
        """
        app = self._build_app(message_handler)
        config = uvicorn.Config(
            app=app,
            host=self._host,
            port=self._port,
            log_config=None,
        )
        self._server = uvicorn.Server(config)
        logger.info("HTTP transport starting on %s:%s", self._host, self._port)
        await self._server.serve()

    async def stop(self) -> None:
        """Signal uvicorn to shut down."""
        if self._server is not None:
            self._server.should_exit = True
            logger.info("HTTP transport stop requested")

    def _build_app(self, message_handler: MessageHandler) -> Starlette:
        """Build the Starlette ASGI application.

        Args:
            message_handler: The handler to dispatch JSON-RPC messages to.

        Returns:
            A configured Starlette application.
        """

        async def _adp_endpoint(request: Request) -> Response:
            """Handle POST /adp requests."""
            content_type = request.headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                return Response(
                    content=_ERR_UNSUPPORTED_MEDIA,
                    media_type="application/json",
                    status_code=415,
                )

            body = await request.body()
            if not body:
                return Response(
                    content=_ERR_EMPTY_BODY,
                    media_type="application/json",
                    status_code=400,
                )

            try:
                body_str = body.decode("utf-8")
            except UnicodeDecodeError:
                return Response(
                    content=_ERR_INVALID_ENCODING,
                    media_type="application/json",
                    status_code=400,
                )

            auth_header = request.headers.get("authorization")
            if auth_header is not None:
                body_str = self._inject_authorization(body_str, auth_header)

            try:
                response = await message_handler(body_str)
            except Exception:
                logger.exception("Unexpected error in message handler")
                return Response(
                    content=_ERR_INTERNAL,
                    media_type="application/json",
                    status_code=500,
                )

            return Response(content=response, media_type="application/json", status_code=200)

        routes = [
            Route("/adp", endpoint=_adp_endpoint, methods=["POST"]),
        ]
        return Starlette(routes=routes)

    @staticmethod
    def _inject_authorization(body_str: str, auth_value: str) -> str:
        """Inject the Authorization header value into JSON-RPC params._meta.

        HTTP clients send credentials in the ``Authorization`` header, but the
        JSON-RPC dispatcher is transport-agnostic.  Injecting the value into
        ``params._meta.authorization`` lets authentication middleware (e.g.
        ``BasicAuthenticator``) work identically for both stdio and HTTP
        transports without coupling the dispatcher to HTTP semantics.

        If JSON parsing fails, the original body is returned unchanged so the
        dispatcher can report the parse error.

        Args:
            body_str: Raw JSON-RPC request body.
            auth_value: Value of the HTTP ``Authorization`` header.

        Returns:
            The (possibly modified) JSON string.
        """
        try:
            data = json.loads(body_str)
        except (json.JSONDecodeError, ValueError):
            return body_str

        if not isinstance(data, dict):
            return body_str

        params = data.setdefault("params", {})
        if not isinstance(params, dict):
            return body_str

        meta = params.setdefault("_meta", {})
        if not isinstance(meta, dict):
            return body_str

        meta["authorization"] = auth_value
        return json.dumps(data)
