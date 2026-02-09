"""ADP Backend implementations."""

from backends.base import Backend, BackendResult
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.registry import BackendRegistry

__all__ = [
    "Backend",
    "BackendRegistry",
    "BackendResult",
    "CredentialResolutionError",
    "resolve_credential",
]
