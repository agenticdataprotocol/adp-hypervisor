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

"""Tests for InitializeHandler."""

import unittest
from typing import Any

from adp_hypervisor.handlers.initialize import InitializeHandler
from adp_hypervisor.protocol.errors import InvalidParamsError
from adp_hypervisor.protocol.types import (
    LATEST_PROTOCOL_VERSION,
    Implementation,
    IntentClass,
    ServerCapabilities,
)


def _make_params(
    protocol_version: str = LATEST_PROTOCOL_VERSION,
    client_name: str = "test-client",
    client_version: str = "1.0.0",
) -> dict[str, Any]:
    return {
        "protocolVersion": protocol_version,
        "capabilities": {},
        "clientInfo": {"name": client_name, "version": client_version},
    }


# =============================================================================
# Method Name Tests
# =============================================================================


class TestInitializeHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = InitializeHandler()
        self.assertEqual(handler.method, "adp.initialize")


# =============================================================================
# Default Behavior Tests
# =============================================================================


class TestInitializeHandlerDefaults(unittest.IsolatedAsyncioTestCase):
    async def test_returns_initialize_result(self) -> None:
        handler = InitializeHandler()
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["protocolVersion"], LATEST_PROTOCOL_VERSION)
        self.assertEqual(data["serverInfo"]["name"], "adp-hypervisor")
        self.assertEqual(data["serverInfo"]["version"], "0.1.0")
        self.assertIn("capabilities", data)

    async def test_default_capabilities_include_all_intent_classes(self) -> None:
        handler = InitializeHandler()
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        supported = data["capabilities"]["supportedIntentClasses"]
        self.assertEqual(set(supported), {"LOOKUP", "QUERY", "INGEST", "REVISE"})

    async def test_no_instructions_by_default(self) -> None:
        handler = InitializeHandler()
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertNotIn("instructions", data)


# =============================================================================
# Custom Configuration Tests
# =============================================================================


class TestInitializeHandlerCustomConfig(unittest.IsolatedAsyncioTestCase):
    async def test_custom_server_info(self) -> None:
        custom_info = Implementation(name="my-server", version="2.0.0")
        handler = InitializeHandler(server_info=custom_info)
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["serverInfo"]["name"], "my-server")
        self.assertEqual(data["serverInfo"]["version"], "2.0.0")

    async def test_custom_capabilities(self) -> None:
        custom_caps = ServerCapabilities(
            supported_intent_classes=[IntentClass.LOOKUP, IntentClass.QUERY]
        )
        handler = InitializeHandler(capabilities=custom_caps)
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(set(data["capabilities"]["supportedIntentClasses"]), {"LOOKUP", "QUERY"})

    async def test_custom_instructions(self) -> None:
        handler = InitializeHandler(instructions="Use this server for data access.")
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["instructions"], "Use this server for data access.")


# =============================================================================
# Version Negotiation Tests
# =============================================================================


class TestInitializeHandlerVersionNegotiation(unittest.IsolatedAsyncioTestCase):
    async def test_supported_version_accepted(self) -> None:
        handler = InitializeHandler()
        result = await handler.handle(_make_params(protocol_version=LATEST_PROTOCOL_VERSION))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["protocolVersion"], LATEST_PROTOCOL_VERSION)

    async def test_unsupported_version_rejected(self) -> None:
        handler = InitializeHandler()
        with self.assertRaisesRegex(InvalidParamsError, "Unsupported protocol version"):
            await handler.handle(_make_params(protocol_version="1999-01-01"))

    async def test_error_message_lists_supported_versions(self) -> None:
        handler = InitializeHandler()
        with self.assertRaisesRegex(InvalidParamsError, LATEST_PROTOCOL_VERSION):
            await handler.handle(_make_params(protocol_version="unknown"))


# =============================================================================
# Parameter Validation Tests
# =============================================================================


class TestInitializeHandlerParamValidation(unittest.IsolatedAsyncioTestCase):
    async def test_missing_protocol_version_raises(self) -> None:
        handler = InitializeHandler()
        with self.assertRaises(ValueError):
            await handler.handle({"capabilities": {}, "clientInfo": {"name": "c", "version": "1"}})

    async def test_missing_client_info_raises(self) -> None:
        handler = InitializeHandler()
        with self.assertRaises(ValueError):
            await handler.handle({"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {}})

    async def test_logs_client_info(self) -> None:
        handler = InitializeHandler()
        with self.assertLogs("adp_hypervisor.handlers.initialize", level="INFO") as cm:
            await handler.handle(_make_params(client_name="agent-x", client_version="3.5.0"))
        log_output = "\n".join(cm.output)
        self.assertIn("agent-x", log_output)
        self.assertIn("3.5.0", log_output)
