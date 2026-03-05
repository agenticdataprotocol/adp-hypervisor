"""ADP Blob Storage backend implementations."""

from adp_hypervisor.protocol.types import Field, FieldType
from backends.blob_storage.backend import BlobStorageBackend
from backends.blob_storage.local import LocalFSBackend

# Convention-based metadata fields shared by all BLOB_STORAGE backends.
# These are injected into schema-less resources at startup so that
# DESCRIBE and VALIDATE handlers can see them.
CONVENTION_FIELDS: list[Field] = [
    Field(
        field_id="path",
        type=FieldType.STRING,
        description="Relative path from the resource source root",
    ),
    Field(
        field_id="size",
        type=FieldType.INTEGER,
        description="Size in bytes (0 for directories)",
    ),
    Field(
        field_id="last_modified",
        type=FieldType.TIMESTAMP,
        description="Last modification time (ISO 8601)",
    ),
    Field(
        field_id="created_at",
        type=FieldType.TIMESTAMP,
        description="Creation time (ISO 8601)",
    ),
    Field(
        field_id="content_type",
        type=FieldType.STRING,
        description="MIME type inferred from file extension",
    ),
    Field(
        field_id="is_directory",
        type=FieldType.BOOLEAN,
        description="Whether the entry is a directory",
    ),
    Field(
        field_id="content",
        type=FieldType.BLOB,
        description="File content (text or base64-encoded binary); used in LOOKUP/INGEST/REVISE",
    ),
    Field(
        field_id="content_encoding",
        type=FieldType.STRING,
        description="Encoding of the content field: 'utf-8' for text, 'base64' for binary",
    ),
]

__all__ = [
    # Base
    "BlobStorageBackend",
    # Implementations
    "LocalFSBackend",
    # Convention fields
    "CONVENTION_FIELDS",
]
