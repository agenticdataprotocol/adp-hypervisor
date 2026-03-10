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

"""
Credential resolution utilities.

Resolves CredentialReference objects from the physical manifest into actual
credential values by reading from environment variables, files, or secret managers.
"""

import logging
import os
from pathlib import Path

from adp_hypervisor.manifest.physical import CredentialReference

logger = logging.getLogger(__name__)


class CredentialResolutionError(Exception):
    """Raised when a credential cannot be resolved."""


def resolve_credential(ref: CredentialReference) -> str:
    """Resolve a credential reference to its actual value.

    Supports the following credential types:
    - ``env``: Read from an environment variable.
    - ``file``: Read from a file on disk.
    - ``secret``: Reserved for secret manager integration (not yet implemented).

    Args:
        ref: The credential reference to resolve.

    Returns:
        The resolved credential value as a string.

    Raises:
        CredentialResolutionError: If the credential cannot be resolved.
        NotImplementedError: If the credential type is ``secret``.
    """
    if ref.type == "env":
        return _resolve_env(ref.key)
    elif ref.type == "file":
        return _resolve_file(ref.key)
    elif ref.type == "secret":
        raise NotImplementedError(
            f"Secret manager credential resolution is not yet implemented "
            f"(manager={ref.manager!r}, key={ref.key!r})"
        )
    else:
        raise CredentialResolutionError(f"Unknown credential type: {ref.type!r}")


def _resolve_env(key: str) -> str:
    """Resolve a credential from an environment variable."""
    value = os.environ.get(key)
    if value is None:
        raise CredentialResolutionError(f"Environment variable not found: {key!r}")
    return value


def _resolve_file(path: str) -> str:
    """Resolve a credential from a file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise CredentialResolutionError(f"Credential file not found: {path!r}")
    try:
        return file_path.read_text().strip()
    except OSError as e:
        raise CredentialResolutionError(f"Failed to read credential file {path!r}: {e}") from e
