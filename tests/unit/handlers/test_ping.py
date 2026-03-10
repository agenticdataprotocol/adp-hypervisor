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
