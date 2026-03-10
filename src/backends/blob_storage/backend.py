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
Blob Storage Backend base class.

Defines the abstract interface that all blob storage backend implementations must
follow. Subclasses handle connection management and intent execution for their
specific blob storage provider (e.g., local filesystem, S3-compatible stores).
"""

from adp_hypervisor.manifest.physical import BackendDefinition
from backends.base import Backend


class BlobStorageBackend(Backend):
    """Base class for blob storage backends.

    Subclasses must implement connection management and intent execution
    for their specific blob storage provider.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
