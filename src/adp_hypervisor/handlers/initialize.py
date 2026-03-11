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
Initialize Handler.

Implements the adp.initialize method which performs protocol version negotiation,
capability exchange, and server info response.
"""

import logging
from typing import Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.protocol.errors import InvalidParamsError
from adp_hypervisor.protocol.types import (
    LATEST_PROTOCOL_VERSION,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    IntentClass,
    ServerCapabilities,
)

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_INFO = Implementation(name="adp-hypervisor", version="0.1.0.dev0")

_DEFAULT_CAPABILITIES = ServerCapabilities(
    supported_intent_classes=[
        IntentClass.LOOKUP,
        IntentClass.QUERY,
        IntentClass.INGEST,
        IntentClass.REVISE,
    ]
)

_SUPPORTED_PROTOCOL_VERSIONS = frozenset({LATEST_PROTOCOL_VERSION})


class InitializeHandler(Handler):
    """Handler for the adp.initialize method.

    Performs protocol version negotiation (strict match), capability exchange,
    and returns server information.
    """

    def __init__(
        self,
        server_info: Implementation | None = None,
        capabilities: ServerCapabilities | None = None,
        instructions: str | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            server_info: Custom server implementation info. Defaults to adp-hypervisor/0.1.0.
            capabilities: Custom server capabilities. Defaults to all intent classes.
            instructions: Optional instructions string returned to the client.
        """
        self._server_info = server_info or _DEFAULT_SERVER_INFO
        self._capabilities = capabilities or _DEFAULT_CAPABILITIES
        self._instructions = instructions

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.initialize"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process an initialize request.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            An InitializeResult with negotiated protocol version, capabilities, and server info.

        Raises:
            InvalidParamsError: If the requested protocol version is not supported.
        """
        request = InitializeRequestParams.model_validate(params)

        logger.info(
            "Initialize request from %s/%s, protocol version: %s",
            request.client_info.name,
            request.client_info.version,
            request.protocol_version,
        )

        if request.protocol_version not in _SUPPORTED_PROTOCOL_VERSIONS:
            supported = ", ".join(sorted(_SUPPORTED_PROTOCOL_VERSIONS))
            raise InvalidParamsError(
                f"Unsupported protocol version: {request.protocol_version!r}. "
                f"Supported versions: {supported}"
            )

        return InitializeResult(
            protocol_version=request.protocol_version,
            capabilities=self._capabilities,
            server_info=self._server_info,
            instructions=self._instructions,
        )
