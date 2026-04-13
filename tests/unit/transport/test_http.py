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

"""Tests for the HTTP Transport."""

import json
import unittest

from httpx import ASGITransport, AsyncClient

from adp_hypervisor.transport.http import HttpTransport

# =============================================================================
# Helpers
# =============================================================================

_VALID_BODY = '{"jsonrpc":"2.0","id":1,"method":"test"}'
_HANDLER_RESPONSE = '{"jsonrpc":"2.0","id":1,"result":{}}'
_JSON_HEADERS = {"Content-Type": "application/json"}


async def _ok_handler(msg: str) -> str:
    """Handler that returns a successful JSON-RPC response."""
    return _HANDLER_RESPONSE


async def _echo_handler(msg: str) -> str:
    """Handler that echoes back whatever it receives."""
    return msg


async def _error_handler(msg: str) -> str:
    """Handler that always raises an exception."""
    raise RuntimeError("boom")


# =============================================================================
# TestHttpTransportApp — ASGI endpoint tests
# =============================================================================


class TestHttpTransportApp(unittest.IsolatedAsyncioTestCase):
    """Tests for the Starlette ASGI application built by HttpTransport."""

    def setUp(self) -> None:
        self.transport = HttpTransport()

    async def _client(self, handler: object = None) -> AsyncClient:
        """Build an httpx AsyncClient wired to the ASGI app.

        Args:
            handler: Optional message handler override.

        Returns:
            An AsyncClient ready to make requests.
        """
        h = handler or _ok_handler
        app = self.transport._build_app(h)  # type: ignore[arg-type,unused-ignore]
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    # --- happy path ---

    async def test_post_adp_valid_request(self) -> None:
        """POST /adp with valid JSON body returns 200 and the handler response."""
        async with await self._client() as client:
            resp = await client.post("/adp", content=_VALID_BODY, headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), json.loads(_HANDLER_RESPONSE))

    # --- content-type checks ---

    async def test_post_adp_wrong_content_type(self) -> None:
        """POST /adp with text/plain returns 415 Unsupported Media Type."""
        async with await self._client() as client:
            resp = await client.post(
                "/adp", content=_VALID_BODY, headers={"Content-Type": "text/plain"}
            )
        self.assertEqual(resp.status_code, 415)
        self.assertIn("Unsupported Media Type", resp.text)

    async def test_post_adp_missing_content_type(self) -> None:
        """POST /adp with no Content-Type header returns 415."""
        async with await self._client() as client:
            resp = await client.post("/adp", content=_VALID_BODY)
        self.assertEqual(resp.status_code, 415)

    # --- body checks ---

    async def test_post_adp_empty_body(self) -> None:
        """POST /adp with empty body returns 400."""
        async with await self._client() as client:
            resp = await client.post("/adp", content=b"", headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Empty request body", resp.text)

    async def test_post_adp_invalid_utf8(self) -> None:
        """POST /adp with invalid UTF-8 body returns 400."""
        async with await self._client() as client:
            resp = await client.post("/adp", content=b"\xff\xfe", headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid UTF-8 encoding", resp.text)

    # --- method checks ---

    async def test_get_adp_method_not_allowed(self) -> None:
        """GET /adp returns 405 Method Not Allowed."""
        async with await self._client() as client:
            resp = await client.get("/adp")
        self.assertEqual(resp.status_code, 405)

    async def test_put_adp_method_not_allowed(self) -> None:
        """PUT /adp returns 405 Method Not Allowed."""
        async with await self._client() as client:
            resp = await client.put("/adp", content=_VALID_BODY, headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 405)

    # --- routing ---

    async def test_unknown_path(self) -> None:
        """POST to an unknown path returns 404."""
        async with await self._client() as client:
            resp = await client.post("/unknown", content=_VALID_BODY, headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 404)

    # --- handler errors ---

    async def test_handler_exception_returns_500(self) -> None:
        """When the handler raises, the server returns 500 with a JSON-RPC internal error."""
        async with await self._client(handler=_error_handler) as client:
            resp = await client.post("/adp", content=_VALID_BODY, headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertEqual(body["error"]["code"], -32603)
        self.assertEqual(body["error"]["message"], "Internal error")

    # --- authorization injection ---

    async def test_authorization_header_injected(self) -> None:
        """POST with Authorization header injects auth into params._meta."""
        async with await self._client(handler=_echo_handler) as client:
            headers = {**_JSON_HEADERS, "Authorization": "Bearer token123"}
            resp = await client.post("/adp", content=_VALID_BODY, headers=headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["params"]["_meta"]["authorization"], "Bearer token123")

    async def test_no_authorization_header_no_injection(self) -> None:
        """POST without Authorization header leaves the body unchanged."""
        async with await self._client(handler=_echo_handler) as client:
            resp = await client.post("/adp", content=_VALID_BODY, headers=_JSON_HEADERS)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body, json.loads(_VALID_BODY))

    async def test_authorization_injection_invalid_json(self) -> None:
        """POST with Authorization + invalid JSON body passes body through unchanged."""
        invalid_body = "not valid json"

        async with await self._client(handler=_echo_handler) as client:
            headers = {**_JSON_HEADERS, "Authorization": "Bearer tok"}
            resp = await client.post("/adp", content=invalid_body, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, invalid_body)


# =============================================================================
# TestHttpTransportInjectAuthorization — static method unit tests
# =============================================================================


class TestHttpTransportInjectAuthorization(unittest.TestCase):
    """Unit tests for HttpTransport._inject_authorization()."""

    def test_inject_into_existing_params(self) -> None:
        """Authorization is added to an existing params._meta dict."""
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test", "params": {"key": "val"}})
        result = json.loads(HttpTransport._inject_authorization(body, "Bearer abc"))
        self.assertEqual(result["params"]["_meta"]["authorization"], "Bearer abc")
        self.assertEqual(result["params"]["key"], "val")

    def test_inject_creates_params_and_meta(self) -> None:
        """When params is missing, params and _meta are created."""
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test"})
        result = json.loads(HttpTransport._inject_authorization(body, "Bearer xyz"))
        self.assertEqual(result["params"]["_meta"]["authorization"], "Bearer xyz")

    def test_inject_invalid_json_passthrough(self) -> None:
        """Invalid JSON body is returned unchanged."""
        raw = "{{not json}}"
        result = HttpTransport._inject_authorization(raw, "Bearer tok")
        self.assertEqual(result, raw)

    def test_inject_non_dict_body_passthrough(self) -> None:
        """A JSON array body is returned unchanged."""
        raw = json.dumps([1, 2, 3])
        result = HttpTransport._inject_authorization(raw, "Bearer tok")
        self.assertEqual(result, raw)


# =============================================================================
# TestHttpTransportLifecycle
# =============================================================================


class TestHttpTransportLifecycle(unittest.IsolatedAsyncioTestCase):
    """Lifecycle tests for HttpTransport."""

    async def test_stop_before_start(self) -> None:
        """Calling stop() before start() should not raise."""
        transport = HttpTransport()
        await transport.stop()
