"""Tests for credential resolution utilities."""

import os
import tempfile
import unittest

from adp_hypervisor.manifest.physical import CredentialReference
from backends.credentials import CredentialResolutionError, resolve_credential

# =============================================================================
# Environment Variable Tests
# =============================================================================


class TestEnvCredential(unittest.TestCase):
    def test_resolve_existing_env_var(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"TEST_DB_PASSWORD": "s3cret"}):
            ref = CredentialReference(type="env", key="TEST_DB_PASSWORD")
            self.assertEqual(resolve_credential(ref), "s3cret")

    def test_missing_env_var_raises(self) -> None:
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            ref = CredentialReference(type="env", key="NONEXISTENT_VAR")
            with self.assertRaisesRegex(
                CredentialResolutionError, "Environment variable not found"
            ):
                resolve_credential(ref)

    def test_empty_env_var_is_valid(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"EMPTY_VAR": ""}):
            ref = CredentialReference(type="env", key="EMPTY_VAR")
            self.assertEqual(resolve_credential(ref), "")


# =============================================================================
# File Credential Tests
# =============================================================================


class TestFileCredential(unittest.TestCase):
    def test_resolve_file_credential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = os.path.join(tmp_dir, "secret.txt")
            with open(secret_file, "w") as f:
                f.write("my-password\n")
            ref = CredentialReference(type="file", key=secret_file)
            self.assertEqual(resolve_credential(ref), "my-password")

    def test_file_content_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_file = os.path.join(tmp_dir, "secret.txt")
            with open(secret_file, "w") as f:
                f.write("  password-with-spaces  \n\n")
            ref = CredentialReference(type="file", key=secret_file)
            self.assertEqual(resolve_credential(ref), "password-with-spaces")

    def test_missing_file_raises(self) -> None:
        ref = CredentialReference(type="file", key="/nonexistent/path/secret.txt")
        with self.assertRaisesRegex(CredentialResolutionError, "Credential file not found"):
            resolve_credential(ref)

    def test_directory_is_not_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ref = CredentialReference(type="file", key=tmp_dir)
            with self.assertRaisesRegex(CredentialResolutionError, "Credential file not found"):
                resolve_credential(ref)


# =============================================================================
# Secret Manager Tests
# =============================================================================


class TestSecretCredential(unittest.TestCase):
    def test_secret_type_not_implemented(self) -> None:
        ref = CredentialReference(
            type="secret", key="prod/db-password", manager="AWS_SECRETS_MANAGER"
        )
        with self.assertRaisesRegex(NotImplementedError, "not yet implemented"):
            resolve_credential(ref)
