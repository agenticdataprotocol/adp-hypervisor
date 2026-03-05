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
