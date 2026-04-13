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

"""Tests for the CLI entry point argument parsing and helpers."""

import unittest

from adp_hypervisor.__main__ import _build_parser

# =============================================================================
# TestCliParser
# =============================================================================


class TestCliParser(unittest.TestCase):
    """Tests for CLI argument parser built by ``_build_parser()``."""

    def setUp(self) -> None:
        self.parser = _build_parser()

    def test_parser_default_transport_is_stdio(self) -> None:
        """Default transport should be 'stdio'."""
        parsed = self.parser.parse_args(["--config", "/dummy"])
        self.assertEqual(parsed.transport, "stdio")

    def test_parser_http_transport(self) -> None:
        """``--transport http`` should be accepted."""
        parsed = self.parser.parse_args(["--config", "/dummy", "--transport", "http"])
        self.assertEqual(parsed.transport, "http")

    def test_parser_host_default(self) -> None:
        """Default host should be '127.0.0.1'."""
        parsed = self.parser.parse_args(["--config", "/dummy"])
        self.assertEqual(parsed.host, "0.0.0.0")

    def test_parser_port_default(self) -> None:
        """Default port should be 8000."""
        parsed = self.parser.parse_args(["--config", "/dummy"])
        self.assertEqual(parsed.port, 8000)

    def test_parser_custom_host_and_port(self) -> None:
        """``--host`` and ``--port`` should override defaults."""
        parsed = self.parser.parse_args(
            ["--config", "/dummy", "--host", "0.0.0.0", "--port", "9090"]
        )
        self.assertEqual(parsed.host, "0.0.0.0")
        self.assertEqual(parsed.port, 9090)


if __name__ == "__main__":
    unittest.main()
