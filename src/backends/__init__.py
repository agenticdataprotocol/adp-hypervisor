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

"""ADP Backend implementations."""

from backends.base import Backend, BackendResult
from backends.blob_storage.local import LocalFSBackend
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.rdbms.backend import RDBMSBackend
from backends.rdbms.postgres import PostgresBackend
from backends.registry import BackendRegistry
from backends.vector.backend import VectorBackend
from backends.vector.pgvector import PgVectorBackend

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
    # Vector
    "VectorBackend",
    "PgVectorBackend",
    # Blob Storage
    "LocalFSBackend",
]
