"""Unit tests for the RDBMS backend modules."""

import unittest

from backends.rdbms.postgres import _inject_password

# =============================================================================
# Password Injection Tests
# =============================================================================


class TestInjectPassword(unittest.TestCase):
    def test_simple_dsn_without_password(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "secret")
        self.assertEqual(result, "postgresql://user:secret@localhost/db")

    def test_simple_dsn_with_existing_password(self) -> None:
        result = _inject_password("postgresql://user:old@localhost/db", "new")
        self.assertEqual(result, "postgresql://user:new@localhost/db")

    def test_password_with_special_characters(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "p@ss:w0rd/foo")
        self.assertIn("p%40ss%3Aw0rd%2Ffoo", result)
        self.assertTrue(result.startswith("postgresql://user:"))
        self.assertIn("@localhost/db", result)

    def test_dsn_with_port(self) -> None:
        result = _inject_password("postgresql://user@localhost:5432/db", "secret")
        self.assertEqual(result, "postgresql://user:secret@localhost:5432/db")

    def test_dsn_with_port_and_existing_password(self) -> None:
        result = _inject_password("postgresql://user:old@localhost:5432/db", "new")
        self.assertEqual(result, "postgresql://user:new@localhost:5432/db")

    def test_dsn_without_host_returns_unchanged(self) -> None:
        result = _inject_password("not-a-url", "secret")
        self.assertEqual(result, "not-a-url")

    def test_password_with_at_sign(self) -> None:
        result = _inject_password("postgresql://user@localhost/db", "p@ss")
        # '@' in password must be encoded so it does not break URL parsing
        self.assertIn("p%40ss", result)
        self.assertEqual(result.count("@"), 1)  # only the delimiter @
