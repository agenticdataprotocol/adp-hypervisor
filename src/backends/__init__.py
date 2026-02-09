"""ADP Backend implementations."""

from backends.base import Backend, BackendResult
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.rdbms.backend import RDBMSBackend
from backends.rdbms.postgres import PostgresBackend
from backends.registry import BackendRegistry

__all__ = [
    # Base
    "Backend",
    "BackendResult",
    # Registry
    "BackendRegistry",
    # Credentials
    "CredentialResolutionError",
    "resolve_credential",
    # RDBMS
    "RDBMSBackend",
    "PostgresBackend",
]
