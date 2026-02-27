"""
MongoDB backend implementation.

Uses motor (async MongoDB driver) for connection pooling and schema discovery
via document sampling.
"""

import logging
import urllib.parse
from typing import Any

from bson import ObjectId
from motor import motor_asyncio

from adp_hypervisor.manifest.physical import BackendDefinition, NOSQLBackendConfig
from adp_hypervisor.protocol.types import Field, FieldType
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.nosql.backend import NOSQLBackend

logger = logging.getLogger(__name__)

# Mapping from Python type names to ADP FieldType.
_TYPE_MAP: dict[str, FieldType] = {
    "str": FieldType.STRING,
    "int": FieldType.INTEGER,
    "float": FieldType.FLOAT,
    "bool": FieldType.BOOLEAN,
    "list": FieldType.JSON,
    "dict": FieldType.JSON,
    "datetime": FieldType.TIMESTAMP,
    "date": FieldType.DATE,
    "bytes": FieldType.BLOB,
    "ObjectId": FieldType.STRING,
}


class MongoDBBackend(NOSQLBackend):
    """MongoDB backend using motor async driver."""

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
        self._client: motor_asyncio.AsyncIOMotorClient[Any] | None = None
        self._db: motor_asyncio.AsyncIOMotorDatabase[Any] | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create a motor client and connect to MongoDB."""
        uri = self._resolve_uri()
        logger.info("Connecting to MongoDB: %s", self.backend_id)
        self._client = motor_asyncio.AsyncIOMotorClient(uri)

        config = self._definition.config
        assert isinstance(config, NOSQLBackendConfig)
        database_name = self._get_database_name()
        self._db = self._client[database_name]

        # Test connection
        await self._client.admin.command("ping")
        logger.info("MongoDB connected for %s", self.backend_id)

    async def disconnect(self) -> None:
        """Close the MongoDB client."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB disconnected for %s", self.backend_id)

    # ------------------------------------------------------------------
    # Schema discovery
    # ------------------------------------------------------------------

    async def get_schema(self, source: str) -> list[Field]:
        """Sample documents and infer schema.

        Args:
            source: The collection name.

        Returns:
            List of field definitions inferred from sampled documents.
        """
        db = self._require_db()
        collection = db[source]

        # Sample documents
        pipeline = [{"$sample": {"size": 100}}]
        cursor = collection.aggregate(pipeline)
        docs = await cursor.to_list(length=100)

        if not docs:
            logger.warning("No documents found in collection %s", source)
            return []

        # Analyze fields
        field_stats: dict[str, dict[str, Any]] = {}
        for doc in docs:
            for key, value in doc.items():
                if key not in field_stats:
                    field_stats[key] = {
                        "types": set(),
                        "samples": [],
                        "count": 0,
                    }
                field_stats[key]["types"].add(type(value).__name__)
                field_stats[key]["count"] += 1
                if len(field_stats[key]["samples"]) < 3:
                    field_stats[key]["samples"].append(self._serialize_value(value))

        # Build Field list
        fields: list[Field] = []
        for field_id, stats in field_stats.items():
            field_type = self._infer_field_type(stats["types"])
            fields.append(
                Field(
                    field_id=field_id,
                    type=field_type,
                    samples=stats["samples"],
                )
            )

        return fields

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def fetch_documents(
        self,
        collection: str,
        filter_query: dict[str, Any],
        projection: dict[str, Any] | None,
        sort: list[tuple[str, int]] | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Execute MongoDB find() and return documents.

        Args:
            collection: The collection name.
            filter_query: The filter/query dict.
            projection: Field projection dict (None for all fields).
            sort: List of (field, direction) tuples.
            limit: Maximum number of documents to return.

        Returns:
            List of documents as dicts.
        """
        db = self._require_db()
        coll = db[collection]

        if limit == 0:
            return []

        # Normalize filter to handle ObjectId
        normalized_filter = self._normalize_filter(filter_query)

        cursor = coll.find(normalized_filter, projection)
        if sort is not None:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)

        docs = await cursor.to_list(length=limit if limit else None)

        # Convert ObjectId to string
        return [self._normalize_document(doc) for doc in docs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_db(self) -> motor_asyncio.AsyncIOMotorDatabase[Any]:
        """Return the database instance, raising if not connected.

        Returns:
            The database instance.

        Raises:
            ConnectionError: If the backend is not connected.
        """
        if self._db is None:
            raise ConnectionError(
                f"MongoDB backend {self.backend_id!r} is not connected. " "Call connect() first."
            )
        return self._db

    def _resolve_uri(self) -> str:
        """Build the connection URI, resolving credentials if configured.

        Returns:
            The MongoDB connection URI.
        """
        config = self._definition.config
        assert isinstance(config, NOSQLBackendConfig)

        # Get URI from config (NOSQLBackendConfig has extra="allow")
        uri: str = str(getattr(config, "uri", "mongodb://localhost:27017"))

        if self._definition.credentials is not None:
            try:
                password = resolve_credential(self._definition.credentials)
                uri = _inject_password(uri, password)
            except CredentialResolutionError:
                logger.warning(
                    "Could not resolve credentials for %s, using URI as-is",
                    self.backend_id,
                )
        return uri

    def _get_database_name(self) -> str:
        """Extract database name from config.

        Returns:
            The database name, defaulting to "default".
        """
        config = self._definition.config
        assert isinstance(config, NOSQLBackendConfig)

        return str(getattr(config, "database", "default"))

    def _normalize_document(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Convert ObjectId and other BSON types to JSON-serializable types.

        Args:
            doc: The document to normalize.

        Returns:
            Normalized document with serializable values.
        """
        result: dict[str, Any] = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = self._normalize_document(value)
            elif isinstance(value, list):
                result[key] = [
                    (
                        self._normalize_document(item)
                        if isinstance(item, dict)
                        else str(item) if isinstance(item, ObjectId) else item
                    )
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def _normalize_filter(
        self, filter_query: dict[str, Any], *, _parent_is_id: bool = False
    ) -> dict[str, Any]:
        """Normalize filter to handle ObjectId conversion.

        Args:
            filter_query: The filter dict to normalize.
            _parent_is_id: Whether the parent key was ``_id``, so string
                values inside operator dicts should be converted to ObjectId.

        Returns:
            Normalized filter with ObjectId conversion for _id field.
        """
        result: dict[str, Any] = {}
        for key, value in filter_query.items():
            is_id_context = _parent_is_id or key == "_id"

            if is_id_context and isinstance(value, str):
                try:
                    result[key] = ObjectId(value)
                except Exception:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._normalize_filter(value, _parent_is_id=is_id_context)
            elif isinstance(value, list):
                result[key] = [
                    (
                        self._normalize_filter(item, _parent_is_id=is_id_context)
                        if isinstance(item, dict)
                        else (
                            self._try_objectid(item)
                            if is_id_context and isinstance(item, str)
                            else item
                        )
                    )
                    for item in value
                ]
            else:
                result[key] = value
        return result

    @staticmethod
    def _try_objectid(value: str) -> ObjectId | str:
        """Try to convert a string to ObjectId, returning original on failure."""
        try:
            return ObjectId(value)
        except Exception:
            return value

    def _serialize_value(self, value: Any) -> Any:
        """Serialize value for samples.

        Args:
            value: The value to serialize.

        Returns:
            Serialized value suitable for JSON.
        """
        if isinstance(value, ObjectId):
            return str(value)
        elif isinstance(value, (dict, list)):
            return str(value)[:50]  # Truncate complex types
        return value

    def _infer_field_type(self, type_names: set[str]) -> FieldType:
        """Infer ADP FieldType from Python type names.

        Args:
            type_names: Set of Python type names observed for this field.

        Returns:
            The inferred ADP FieldType.
        """
        # If multiple types, prefer more specific types
        if "ObjectId" in type_names:
            return FieldType.STRING
        if "datetime" in type_names:
            return FieldType.TIMESTAMP
        if "date" in type_names:
            return FieldType.DATE
        if "bool" in type_names:
            return FieldType.BOOLEAN
        if "float" in type_names:
            return FieldType.FLOAT
        if "int" in type_names:
            return FieldType.INTEGER
        if "str" in type_names:
            return FieldType.STRING
        if "list" in type_names or "dict" in type_names:
            return FieldType.JSON
        if "bytes" in type_names:
            return FieldType.BLOB

        # Default to STRING
        return FieldType.STRING


def _inject_password(uri: str, password: str) -> str:
    """Inject password into a MongoDB URI.

    Uses ``urllib.parse`` to safely handle special characters in passwords
    and complex URI formats.

    Args:
        uri: The MongoDB connection URI.
        password: The password to inject.

    Returns:
        The URI with the password injected.
    """
    parsed = urllib.parse.urlparse(uri)
    if not parsed.scheme or not parsed.hostname:
        return uri

    # Extract username from existing netloc or use empty string
    username = parsed.username or ""

    replaced = parsed._replace(
        netloc=f"{urllib.parse.quote(username, safe='')}"
        f":{urllib.parse.quote(password, safe='')}"
        f"@{parsed.hostname}"
        f"{f':{parsed.port}' if parsed.port else ''}"
    )
    return urllib.parse.urlunparse(replaced)
