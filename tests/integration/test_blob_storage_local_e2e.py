"""End-to-end integration tests for the local filesystem BLOB_STORAGE backend.

Exercises the full JSON-RPC request flow through the ADPServer with an
in-memory transport and a real temporary directory:
discover → describe → execute (QUERY / LOOKUP / INGEST / REVISE).

No external dependencies (containers, databases) are required.
"""

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.server import ADPServer
from adp_hypervisor.transport.base import Transport

# =============================================================================
# Helpers
# =============================================================================

_RESOURCE_ID = "com.test:local_files"


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

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def receive(self) -> Any:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._requests.get(), timeout=0.5)
                yield msg
            except TimeoutError:
                if not self._running:
                    break

    async def send(self, message: str) -> None:
        self._responses.append(message)

    def enqueue(self, message: str) -> None:
        self._requests.put_nowait(message)


def _write_manifest_files(manifest_dir: Path, data_root: str) -> None:
    """Write physical/semantic/policy manifests for a BLOB_STORAGE local backend."""
    physical = {
        "version": "1.0.0",
        "backends": [
            {
                "id": "test_local",
                "type": "BLOB_STORAGE",
                "provider": "local",
                "config": {
                    "type": "BLOB_STORAGE",
                    "uri": data_root,
                    "autoCreateSource": True,
                },
            }
        ],
    }
    semantic = {
        "version": "1.0.0",
        "resources": [
            {
                "resourceId": _RESOURCE_ID,
                "intentClasses": ["LOOKUP", "QUERY", "INGEST", "REVISE"],
                "version": 1,
                "description": "Test local filesystem resource",
                "backendId": "test_local",
                "sourceDefinition": {
                    "source": "docs",
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

    for name, data in [
        ("physical.yaml", physical),
        ("semantic.yaml", semantic),
        ("policy.yaml", policy),
    ]:
        with open(manifest_dir / name, "w") as f:
            yaml.dump(data, f)


def _seed_files(data_root: Path) -> None:
    """Create a ``docs/`` source directory with sample files."""
    docs = data_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "readme.txt").write_text("Hello, ADP!")
    (docs / "notes.md").write_text("# Notes\nSome notes here.")

    sub = docs / "reports"
    sub.mkdir()
    (sub / "q1.csv").write_text("a,b\n1,2")


# =============================================================================
# E2E Tests
# =============================================================================


class TestBlobStorageLocalE2E(unittest.IsolatedAsyncioTestCase):
    """E2E tests for BLOB_STORAGE + local provider through the ADP server."""

    transport: _InMemoryTransport
    server: ADPServer
    data_root: Path

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmpdir_path = Path(self._tmpdir.name)

        self.data_root = tmpdir_path / "storage"
        self.data_root.mkdir()

        manifest_dir = tmpdir_path / "manifests"
        manifest_dir.mkdir()

        _seed_files(self.data_root)
        _write_manifest_files(manifest_dir, str(self.data_root))

        self.transport = _InMemoryTransport()
        provider = YamlManifestProvider(
            physical_path=manifest_dir / "physical.yaml",
            semantic_path=manifest_dir / "semantic.yaml",
            policy_path=manifest_dir / "policy.yaml",
        )
        self.server = ADPServer(manifest_provider=provider, transport=self.transport)

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        self._tmpdir.cleanup()

    async def _send(self, requests: list[str]) -> list[dict[str, Any]]:
        """Start the server, send requests, and return parsed responses."""
        for req in requests:
            self.transport.enqueue(req)

        server_task = asyncio.create_task(self.server.start())

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

    async def test_discover_includes_blob_resource(self) -> None:
        """DISCOVER must list the BLOB_STORAGE resource."""
        responses = await self._send([_jsonrpc_request("adp.discover", {})])
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)

        resources = resp["result"]["resources"]
        resource_ids = [r["resourceId"] for r in resources]
        self.assertIn(_RESOURCE_ID, resource_ids)

    async def test_describe_returns_convention_fields(self) -> None:
        """DESCRIBE must return convention fields injected at startup."""
        responses = await self._send(
            [
                _jsonrpc_request(
                    "adp.describe",
                    {"resourceId": _RESOURCE_ID, "intentClass": "QUERY"},
                )
            ]
        )
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)

        contract = resp["result"]["usageContract"]
        field_ids = {f["fieldId"] for f in contract["fields"]}
        expected = {
            "path",
            "size",
            "last_modified",
            "created_at",
            "content_type",
            "is_directory",
            "content",
            "content_encoding",
        }
        self.assertEqual(field_ids, expected)

    async def test_execute_query(self) -> None:
        """QUERY must return metadata rows for files in the source directory."""
        responses = await self._send(
            [
                _jsonrpc_request(
                    "adp.execute",
                    {
                        "intent": {
                            "intentClass": "QUERY",
                            "resourceId": _RESOURCE_ID,
                            "predicates": {
                                "op": "AND",
                                "predicates": [
                                    {"fieldId": "size", "op": "GTE", "value": 0},
                                    {"fieldId": "size", "op": "GTE", "value": 0},
                                ],
                            },
                        },
                    },
                )
            ]
        )
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)

        rows = resp["result"]["results"]
        paths = sorted(r["path"] for r in rows)
        self.assertEqual(paths, ["notes.md", "readme.txt", "reports"])

    async def test_execute_lookup(self) -> None:
        """LOOKUP must return file content and metadata."""
        responses = await self._send(
            [
                _jsonrpc_request(
                    "adp.execute",
                    {
                        "intent": {
                            "intentClass": "LOOKUP",
                            "resourceId": _RESOURCE_ID,
                            "key": {"fieldId": "path", "value": "readme.txt"},
                        },
                    },
                )
            ]
        )
        self.assertEqual(len(responses), 1)
        resp = responses[0]
        self.assertNotIn("error", resp)

        results = resp["result"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Hello, ADP!")
        self.assertEqual(results[0]["content_encoding"], "utf-8")
        self.assertEqual(results[0]["path"], "readme.txt")

    async def test_execute_ingest_then_lookup(self) -> None:
        """INGEST creates a new file; LOOKUP verifies its content."""
        ingest_req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "INGEST",
                    "resourceId": _RESOURCE_ID,
                    "payload": [{"path": "new_file.txt", "content": "fresh content"}],
                },
            },
            rid=1,
        )
        lookup_req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "LOOKUP",
                    "resourceId": _RESOURCE_ID,
                    "key": {"fieldId": "path", "value": "new_file.txt"},
                },
            },
            rid=2,
        )

        responses = await self._send([ingest_req, lookup_req])
        self.assertEqual(len(responses), 2)

        ingest_resp = responses[0]
        self.assertNotIn("error", ingest_resp)

        lookup_resp = responses[1]
        self.assertNotIn("error", lookup_resp)
        self.assertEqual(lookup_resp["result"]["results"][0]["content"], "fresh content")

    async def test_execute_revise_then_lookup(self) -> None:
        """REVISE overwrites a file; LOOKUP verifies the new content."""
        revise_req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "REVISE",
                    "resourceId": _RESOURCE_ID,
                    "predicates": {
                        "op": "AND",
                        "predicates": [
                            {"fieldId": "path", "op": "EQ", "value": "readme.txt"},
                            {"fieldId": "is_directory", "op": "EQ", "value": False},
                        ],
                    },
                    "payload": {"content": "Updated content!"},
                },
            },
            rid=1,
        )
        lookup_req = _jsonrpc_request(
            "adp.execute",
            {
                "intent": {
                    "intentClass": "LOOKUP",
                    "resourceId": _RESOURCE_ID,
                    "key": {"fieldId": "path", "value": "readme.txt"},
                },
            },
            rid=2,
        )

        responses = await self._send([revise_req, lookup_req])
        self.assertEqual(len(responses), 2)

        revise_resp = responses[0]
        self.assertNotIn("error", revise_resp)

        lookup_resp = responses[1]
        self.assertNotIn("error", lookup_resp)
        self.assertEqual(lookup_resp["result"]["results"][0]["content"], "Updated content!")

    async def test_full_flow(self) -> None:
        """DISCOVER → DESCRIBE → QUERY → LOOKUP end-to-end in a single session."""
        requests = [
            _jsonrpc_request("adp.discover", {}, rid=1),
            _jsonrpc_request(
                "adp.describe",
                {"resourceId": _RESOURCE_ID, "intentClass": "QUERY"},
                rid=2,
            ),
            _jsonrpc_request(
                "adp.execute",
                {
                    "intent": {
                        "intentClass": "QUERY",
                        "resourceId": _RESOURCE_ID,
                        "predicates": {
                            "op": "AND",
                            "predicates": [
                                {
                                    "fieldId": "is_directory",
                                    "op": "EQ",
                                    "value": False,
                                },
                                {
                                    "fieldId": "size",
                                    "op": "GTE",
                                    "value": 0,
                                },
                            ],
                        },
                    },
                },
                rid=3,
            ),
            _jsonrpc_request(
                "adp.execute",
                {
                    "intent": {
                        "intentClass": "LOOKUP",
                        "resourceId": _RESOURCE_ID,
                        "key": {"fieldId": "path", "value": "notes.md"},
                    },
                },
                rid=4,
            ),
        ]

        responses = await self._send(requests)
        self.assertEqual(len(responses), 4)

        for i, resp in enumerate(responses):
            self.assertNotIn("error", resp, f"Response {i + 1} has an error: {resp}")
            self.assertEqual(resp["id"], i + 1)

        # DISCOVER — resource listed
        resource_ids = [r["resourceId"] for r in responses[0]["result"]["resources"]]
        self.assertIn(_RESOURCE_ID, resource_ids)

        # DESCRIBE — convention fields present
        field_ids = {f["fieldId"] for f in responses[1]["result"]["usageContract"]["fields"]}
        self.assertIn("path", field_ids)
        self.assertIn("size", field_ids)
        self.assertIn("is_directory", field_ids)

        # QUERY — only files (no directories)
        query_rows = responses[2]["result"]["results"]
        self.assertTrue(all(not r["is_directory"] for r in query_rows))
        query_paths = sorted(r["path"] for r in query_rows)
        self.assertEqual(query_paths, ["notes.md", "readme.txt"])

        # LOOKUP — file content
        lookup_results = responses[3]["result"]["results"]
        self.assertEqual(len(lookup_results), 1)
        self.assertIn("# Notes", lookup_results[0]["content"])
