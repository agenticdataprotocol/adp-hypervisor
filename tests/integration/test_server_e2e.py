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

"""End-to-end integration tests for the ADP Hypervisor server.

Uses testcontainers to spin up a real PostgreSQL instance and exercises
the full JSON-RPC request flow through the ADPServer with StdioTransport:
initialize → ping → discover → describe → validate → execute.
"""

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from testcontainers.postgres import PostgresContainer

from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.server import ADPServer
from adp_hypervisor.transport.base import MessageHandler, Transport

# =============================================================================
# Module-level fixtures
# =============================================================================

_pg_container: PostgresContainer | None = None
_pg_dsn: str | None = None


def setUpModule() -> None:
    """Start a PostgreSQL container for the test module."""
    global _pg_container, _pg_dsn  # noqa: PLW0603
    _pg_container = PostgresContainer("postgres:16-alpine")
    _pg_container.start()
    url = _pg_container.get_connection_url()
    dsn = url.split("://", 1)[-1]
    _pg_dsn = f"postgresql://{dsn}"


def tearDownModule() -> None:
    """Stop the PostgreSQL container."""
    global _pg_container  # noqa: PLW0603
    if _pg_container is not None:
        _pg_container.stop()
        _pg_container = None


# =============================================================================
# Helpers
# =============================================================================

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    age  INTEGER NOT NULL
);
INSERT INTO users (name, age) VALUES
    ('Alice', 30),
    ('Bob', 25),
    ('Charlie', 35);
"""


def _get_pg_dsn() -> str:
    if _pg_dsn is None:
        raise RuntimeError("setUpModule was not called")
    return _pg_dsn


async def _seed_database(dsn: str) -> None:
    """Create the test table and seed data."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP TABLE IF EXISTS users")
        await conn.execute(_TABLE_DDL)
    finally:
        await conn.close()


def _write_manifest_files(tmpdir: Path, dsn: str) -> None:
    """Write physical.yaml, semantic.yaml, policy.yaml to tmpdir."""
    physical = {
        "version": "1.0.0",
        "backends": [
            {
                "id": "test_pg",
                "type": "RDBMS",
                "provider": "postgresql",
                "config": {"type": "RDBMS", "uri": dsn},
            }
        ],
    }
    semantic = {
        "version": "1.0.0",
        "resources": [
            {
                "resourceId": "com.test:users",
                "intentClasses": ["LOOKUP", "QUERY"],
                "version": 1,
                "description": "Test users table",
                "backendId": "test_pg",
                "sourceDefinition": {
                    "source": "users",
                    "fields": [
                        {"fieldId": "id", "type": "INTEGER", "description": "Primary key"},
                        {"fieldId": "name", "type": "STRING", "description": "User name"},
                        {"fieldId": "age", "type": "INTEGER", "description": "User age"},
                    ],
                },
            }
        ],
    }
    policy: dict[str, object] = {
        "version": "1.0.0",
        "policies": [
            {
                "type": "ACCESS",
                "resourceSelector": "*",
                "roles": [{"role": "default", "allowedIntents": ["*"]}],
            }
        ],
    }

    import yaml

    for name, data in [
        ("physical.yaml", physical),
        ("semantic.yaml", semantic),
        ("policy.yaml", policy),
    ]:
        with open(tmpdir / name, "w") as f:
            yaml.dump(data, f)


def _basic_auth(username: str, password: str = "") -> str:
    """Build a Basic Auth header value."""
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


_DEFAULT_META: dict[str, str] = {"authorization": _basic_auth("testuser")}


def _jsonrpc_request(method: str, params: dict[str, Any] | None = None, rid: int = 1) -> str:
    """Build a JSON-RPC 2.0 request string."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = {**params, "_meta": _DEFAULT_META}
    else:
        msg["params"] = {"_meta": _DEFAULT_META}
    return json.dumps(msg)


class _InMemoryTransport(Transport):
    """In-memory transport that queues request/response messages for testing."""

    def __init__(self) -> None:
        self._requests: asyncio.Queue[str] = asyncio.Queue()
        self._responses: list[str] = []
        self._running = False

    async def start(self, message_handler: MessageHandler) -> None:
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(self._requests.get(), timeout=0.5)
                response = await message_handler(msg)
                self._responses.append(response)
            except TimeoutError:
                if not self._running:
                    break

    async def stop(self) -> None:
        self._running = False

    def enqueue(self, message: str) -> None:
        """Enqueue a request message to be received by the server."""
        self._requests.put_nowait(message)

    def get_response(self, index: int = -1) -> dict[str, Any]:
        """Get a parsed response by index."""
        return json.loads(self._responses[index])


# =============================================================================
# E2E Test
# =============================================================================


class TestServerE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests for the full ADP server request flow."""

    tmpdir: tempfile.TemporaryDirectory[str]
    transport: _InMemoryTransport
    server: ADPServer

    async def asyncSetUp(self) -> None:
        dsn = _get_pg_dsn()
        await _seed_database(dsn)

        self.tmpdir = tempfile.TemporaryDirectory()
        tmpdir_path = Path(self.tmpdir.name)
        _write_manifest_files(tmpdir_path, dsn)

        self.transport = _InMemoryTransport()
        provider = YamlManifestProvider(
            physical_path=tmpdir_path / "physical.yaml",
            semantic_path=tmpdir_path / "semantic.yaml",
            policy_path=tmpdir_path / "policy.yaml",
        )
        self.server = ADPServer(manifest_provider=provider, transport=self.transport)

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        self.tmpdir.cleanup()

    async def _start_server_and_send(self, requests: list[str]) -> list[dict[str, Any]]:
        """Start the server, send requests, and return responses."""
        for req in requests:
            self.transport.enqueue(req)

        server_task = asyncio.create_task(self.server.start())

        # Wait for all responses
        for _ in range(50):
            await asyncio.sleep(0.1)
            if len(self.transport._responses) >= len(requests):
                break

        await self.server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        return [json.loads(r) for r in self.transport._responses]

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    async def test_initialize(self) -> None:
        """Test the full initialize handshake."""
        req = _jsonrpc_request(
            "adp.initialize",
            {
                "protocolVersion": "2026-01-20",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        self.assertEqual(resp["result"]["protocolVersion"], "2026-01-20")
        self.assertIn("serverInfo", resp["result"])
        self.assertIn("capabilities", resp["result"])

    async def test_ping(self) -> None:
        """Test the ping health check."""
        req = _jsonrpc_request("adp.ping", {})
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        self.assertNotIn("error", responses[0])

    async def test_discover(self) -> None:
        """Test resource discovery."""
        req = _jsonrpc_request("adp.discover", {})
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        resources = resp["result"]["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["resourceId"], "com.test:users")

    async def test_describe(self) -> None:
        """Test resource description with usage contract."""
        req = _jsonrpc_request(
            "adp.describe",
            {"resourceId": "com.test:users", "intentClass": "QUERY"},
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        contract = resp["result"]["usageContract"]
        self.assertIn("fields", contract)
        self.assertEqual(len(contract["fields"]), 3)
        self.assertIn("capabilities", contract)

    async def test_validate(self) -> None:
        """Test intent validation."""
        req = _jsonrpc_request(
            "adp.validate",
            {
                "intent": {
                    "intentClass": "QUERY",
                    "resourceId": "com.test:users",
                    "predicates": {
                        "op": "AND",
                        "predicates": [
                            {"fieldId": "age", "op": "GTE", "value": 0},
                            {"fieldId": "age", "op": "LTE", "value": 200},
                        ],
                    },
                },
            },
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        self.assertTrue(resp["result"]["valid"])

    async def test_execute_query(self) -> None:
        """Test executing a QUERY intent against the real database."""
        req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "QUERY",
                    "resourceId": "com.test:users",
                    "predicates": {
                        "op": "AND",
                        "predicates": [
                            {"fieldId": "age", "op": "GTE", "value": 0},
                            {"fieldId": "age", "op": "LTE", "value": 200},
                        ],
                    },
                },
            },
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        self.assertEqual(len(resp["result"]["results"]), 3)

    async def test_execute_lookup(self) -> None:
        """Test executing a LOOKUP intent against the real database."""
        req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "LOOKUP",
                    "resourceId": "com.test:users",
                    "key": {"fieldId": "id", "value": 1},
                },
            },
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)
        self.assertEqual(len(resp["result"]["results"]), 1)
        self.assertEqual(resp["result"]["results"][0]["name"], "Alice")

    async def test_full_flow(self) -> None:
        """Test the complete flow: initialize → ping → discover → describe → execute."""
        requests = [
            _jsonrpc_request(
                "adp.initialize",
                {
                    "protocolVersion": "2026-01-20",
                    "capabilities": {},
                    "clientInfo": {"name": "e2e-test", "version": "1.0"},
                },
                rid=1,
            ),
            _jsonrpc_request("adp.ping", {}, rid=2),
            _jsonrpc_request("adp.discover", {}, rid=3),
            _jsonrpc_request(
                "adp.describe",
                {"resourceId": "com.test:users", "intentClass": "QUERY"},
                rid=4,
            ),
            _jsonrpc_request(
                "adp.execute",
                {
                    "intent": {
                        "intentClass": "QUERY",
                        "resourceId": "com.test:users",
                        "predicates": {
                            "op": "AND",
                            "predicates": [
                                {"fieldId": "name", "op": "EQ", "value": "Alice"},
                                {"fieldId": "age", "op": "GTE", "value": 0},
                            ],
                        },
                        "projections": ["name", "age"],
                    },
                },
                rid=5,
            ),
        ]

        responses = await self._start_server_and_send(requests)
        self.assertEqual(len(responses), 5)

        # All responses should be successful
        for i, resp in enumerate(responses):
            self.assertNotIn("error", resp, f"Response {i + 1} has an error: {resp}")
            self.assertEqual(resp["id"], i + 1)

        # Verify initialize
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2026-01-20")

        # Verify discover
        resources = responses[2]["result"]["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["resourceId"], "com.test:users")

        # Verify describe
        contract = responses[3]["result"]["usageContract"]
        field_ids = [f["fieldId"] for f in contract["fields"]]
        self.assertEqual(field_ids, ["id", "name", "age"])

        # Verify execute
        results = responses[4]["result"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Alice")
        self.assertEqual(results[0]["age"], 30)

    async def test_error_resource_not_found(self) -> None:
        """Test error handling for a non-existent resource."""
        req = _jsonrpc_request(
            "adp.describe",
            {"resourceId": "com.test:nonexistent", "intentClass": "QUERY"},
        )
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32001)

    async def test_error_method_not_found(self) -> None:
        """Test error handling for an unknown method."""
        req = _jsonrpc_request("adp.unknown", {})
        responses = await self._start_server_and_send([req])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)

    async def test_error_invalid_request_includes_structured_validation_details(self) -> None:
        """Test invalid request envelope errors returned by the real server."""
        request = json.dumps({"jsonrpc": "2.0"})

        responses = await self._start_server_and_send([request])

        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertIsNone(resp["id"])
        self.assertEqual(resp["error"]["code"], -32600)
        self.assertEqual(
            resp["error"]["message"],
            "Invalid request: `id`: Field required; `method`: Field required.",
        )
        self.assertEqual(
            resp["error"]["data"],
            {
                "model": "JSONRPCRequest",
                "validationErrors": [
                    {"path": "id", "message": "Field required", "type": "missing"},
                    {"path": "method", "message": "Field required", "type": "missing"},
                ],
            },
        )
        self.assertNotIn("pydantic.dev", resp["error"]["message"])

    async def test_error_invalid_request_id_includes_structured_validation_details(self) -> None:
        """Test invalid request id type errors returned by the real server."""
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1.5,
                "method": "adp.ping",
                "params": {"_meta": _DEFAULT_META},
            }
        )

        responses = await self._start_server_and_send([request])

        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertIsNone(resp["id"])
        self.assertEqual(resp["error"]["code"], -32600)
        # Pydantic emits one error per union branch (id.int and id.str)
        validation_errors = resp["error"]["data"]["validationErrors"]
        self.assertEqual(len(validation_errors), 2)
        self.assertEqual(validation_errors[0]["path"], "id.int")
        self.assertEqual(validation_errors[1]["path"], "id.str")
        self.assertNotIn("pydantic.dev", resp["error"]["message"])

    async def test_error_invalid_params_includes_structured_validation_details(self) -> None:
        """Test invalid params errors returned by the real server."""
        request = _jsonrpc_request(
            "adp.initialize",
            {
                "protocolVersion": 123,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        )

        responses = await self._start_server_and_send([request])

        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["error"]["code"], -32602)
        self.assertEqual(
            resp["error"]["message"],
            "Invalid params: `protocolVersion`: Input should be a valid string.",
        )
        self.assertEqual(
            resp["error"]["data"],
            {
                "model": "InitializeRequestParams",
                "validationErrors": [
                    {
                        "path": "protocolVersion",
                        "message": "Input should be a valid string",
                        "type": "string_type",
                    }
                ],
            },
        )
        self.assertNotIn("pydantic.dev", resp["error"]["message"])
