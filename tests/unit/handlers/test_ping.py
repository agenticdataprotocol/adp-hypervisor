"""Tests for PingHandler."""

import unittest

from pydantic import BaseModel

from adp_hypervisor.handlers.ping import PingHandler

# =============================================================================
# Method Name Tests
# =============================================================================


class TestPingHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = PingHandler()
        self.assertEqual(handler.method, "adp.ping")


# =============================================================================
# Handle Tests
# =============================================================================


class TestPingHandlerHandle(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_result(self) -> None:
        handler = PingHandler()
        result = await handler.handle({})

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data, {})

    async def test_accepts_none_params(self) -> None:
        handler = PingHandler()
        result = await handler.handle({})
        self.assertIsNotNone(result)

    async def test_result_is_valid_base_model(self) -> None:
        handler = PingHandler()
        result = await handler.handle({})
        self.assertIsInstance(result, BaseModel)
