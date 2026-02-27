"""
MongoDB backend implementation.

Uses motor (async MongoDB driver) for connection pooling and schema discovery
via document sampling.
"""

import logging
import re
import urllib.parse
from typing import Any

from bson import ObjectId
from motor import motor_asyncio

from adp_hypervisor.manifest.index import get_global_manifest_index
from adp_hypervisor.manifest.physical import BackendDefinition, NOSQLBackendConfig
from adp_hypervisor.protocol.types import (
    IngestIntent,
    Intent,
    LogicOperator,
    LookupIntent,
    Predicate,
    PredicateGroup,
    PredicateOperator,
    QueryIntent,
    ReviseIntent,
)
from backends.base import BackendResult
from backends.credentials import CredentialResolutionError, resolve_credential
from backends.nosql.backend import NOSQLBackend

logger = logging.getLogger(__name__)

# Mapping from ADP PredicateOperator to MongoDB query operators.
_OPERATOR_MAP: dict[PredicateOperator, str] = {
    PredicateOperator.EQ: "$eq",
    PredicateOperator.NEQ: "$ne",
    PredicateOperator.GT: "$gt",
    PredicateOperator.LT: "$lt",
    PredicateOperator.GTE: "$gte",
    PredicateOperator.LTE: "$lte",
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
    # Backend interface implementation
    # ------------------------------------------------------------------

    async def execute(self, intent: Intent) -> BackendResult:
        """Translate intent to query and execute it.

        Args:
            intent: The intent to execute.

        Returns:
            The execution result containing rows and optional metadata.
        """
        manifest_index = get_global_manifest_index()
        resource = manifest_index.get_resource(intent.resource_id)
        if resource is None:
            raise ValueError(f"Resource not found for intent.resource_id={intent.resource_id!r}")
        source = resource.source_definition.source
        if not source:
            raise ValueError(f"Resource {resource.resource_id!r} has no source definitions")
        filter_query, projection, sort, limit = self._intent_to_query(source, intent)
        logger.debug(
            "Executing query on %s: filter=%s, projection=%s, sort=%s, limit=%s",
            source,
            filter_query,
            projection,
            sort,
            limit,
        )
        rows = await self._fetch_documents(source, filter_query, projection, sort, limit)
        return BackendResult(rows=rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _intent_to_query(
        self, source: str, intent: Intent
    ) -> tuple[dict[str, Any], dict[str, Any] | None, list[tuple[str, int]] | None, int | None]:
        """Translate intent to query components.

        Args:
            source: The source identifier.
            intent: The intent to translate.

        Returns:
            Tuple of (filter_query, projection, sort, limit).

        Raises:
            NotImplementedError: If the intent type is not supported.
            ValueError: If the intent type is unknown.
        """
        if isinstance(intent, LookupIntent):
            filter_query = self._build_lookup_query(intent)
            projection = self._build_projection(intent.projections)
            return filter_query, projection, None, None

        elif isinstance(intent, QueryIntent):
            filter_query = self._build_query_filter(intent.predicates)
            projection = self._build_projection(intent.projections)
            sort = self._build_sort(intent.order_by)
            limit = intent.limit
            return filter_query, projection, sort, limit

        elif isinstance(intent, (IngestIntent, ReviseIntent)):
            raise NotImplementedError(
                f"{intent.intent_class} is not yet supported for NoSQL backends"
            )

        raise ValueError(f"Unknown intent type: {type(intent).__name__}")

    def _build_lookup_query(self, intent: LookupIntent) -> dict[str, Any]:
        """Translate LOOKUP intent to filter dict.

        Args:
            intent: The LOOKUP intent.

        Returns:
            Filter dict for the lookup query.
        """
        return {intent.key.field_id: intent.key.value}

    def _build_query_filter(self, group: PredicateGroup) -> dict[str, Any]:
        """Translate QUERY predicates to filter dict.

        Args:
            group: The predicate group to translate.

        Returns:
            Filter dict for the query.
        """
        parts: list[dict[str, Any]] = []

        for pred in group.predicates:
            if isinstance(pred, PredicateGroup):
                nested = self._build_query_filter(pred)
                if nested:
                    parts.append(nested)
            elif isinstance(pred, Predicate):
                parts.append(self._translate_predicate(pred))

        if not parts:
            return {}

        if group.op == LogicOperator.AND:
            if len(parts) == 1:
                return parts[0]
            return {"$and": parts}
        elif group.op == LogicOperator.OR:
            if len(parts) == 1:
                return parts[0]
            return {"$or": parts}
        elif group.op == LogicOperator.NOT:
            if len(parts) == 1:
                return {"$nor": parts}
            return {"$nor": parts}

        return {}

    def _translate_predicate(self, pred: Predicate) -> dict[str, Any]:
        """Translate single predicate to query operator.

        Args:
            pred: The predicate to translate.

        Returns:
            Query dict for the predicate.

        Raises:
            ValueError: If the operator is not supported or value is invalid.
        """
        field = pred.field_id
        op = pred.op
        value = pred.value

        if op == PredicateOperator.IN:
            if not isinstance(value, list):
                raise ValueError(f"IN operator requires a list value, got {type(value).__name__}")
            if not value:
                raise ValueError("IN operator requires a non-empty list")
            return {field: {"$in": value}}

        if op == PredicateOperator.CONTAINS:
            escaped = re.escape(str(value))
            return {field: {"$regex": escaped, "$options": "i"}}

        if op in (PredicateOperator.LIKE, PredicateOperator.ILIKE):
            pattern = _like_to_regex(str(value))
            if op == PredicateOperator.ILIKE:
                return {field: {"$regex": pattern, "$options": "i"}}
            return {field: {"$regex": pattern}}

        mongo_op = _OPERATOR_MAP.get(op)
        if mongo_op is None:
            raise ValueError(f"Unsupported predicate operator for NoSQL: {op}")

        return {field: {mongo_op: value}}

    def _build_projection(self, projections: list[str] | None) -> dict[str, Any] | None:
        """Build projection dict from field list.

        Args:
            projections: List of field names to project, or None for all fields.

        Returns:
            Projection dict, or None for all fields.
        """
        if not projections:
            return None

        projection = {field: 1 for field in projections}

        if "_id" not in projections:
            projection["_id"] = 0

        return projection

    def _build_sort(self, order_by: list[Any] | None) -> list[tuple[str, int]] | None:
        """Build sort list from order_by specification.

        Args:
            order_by: List of SortOrder objects, or None.

        Returns:
            List of (field, direction) tuples, or None.
        """
        if not order_by:
            return None
        return [(s.field_id, 1 if s.direction == "ASC" else -1) for s in order_by]

    async def _fetch_documents(
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


def _like_to_regex(pattern: str) -> str:
    """Convert a SQL LIKE pattern to a MongoDB-compatible regex.

    Splits on SQL wildcards (``%`` and ``_``), escapes regex metacharacters
    in the literal segments, then reassembles with regex equivalents and anchors.

    Args:
        pattern: The SQL LIKE pattern.

    Returns:
        An anchored regex string equivalent to the LIKE pattern.
    """
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "%":
            parts.append(".*")
            i += 1
        elif pattern[i] == "_":
            parts.append(".")
            i += 1
        else:
            j = i
            while j < len(pattern) and pattern[j] not in ("%", "_"):
                j += 1
            parts.append(re.escape(pattern[i:j]))
            i = j
    return "^" + "".join(parts) + "$"
