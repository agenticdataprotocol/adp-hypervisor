"""ADP Backend implementations."""

from backends.base import Backend, BackendResult
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.nosql.backend import NOSQLBackend
from backends.nosql.mongodb import MongoDBBackend
from backends.posix.backend import POSIXBackend
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
    # NoSQL
    "NOSQLBackend",
    "MongoDBBackend",
    # POSIX
    "POSIXBackend",
]
