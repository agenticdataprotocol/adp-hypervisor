"""
Discover Handler.

Implements the adp.discover method which allows clients to browse
available resources with optional filtering and cursor-based pagination.
"""

from __future__ import annotations

import base64
import binascii
import logging
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import InvalidParamsError
from adp_hypervisor.protocol.types import (
    DiscoverFilter,
    DiscoverRequestParams,
    DiscoverResult,
    IntentClass,
    Resource,
)

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex
    from adp_hypervisor.manifest.semantic import CuratedResource

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise InvalidParamsError(f"Invalid cursor: {cursor!r}") from e
    if offset < 0:
        raise InvalidParamsError(f"Invalid cursor: {cursor!r}")
    return offset


_ALL_CONCRETE_INTENT_CLASSES = [
    IntentClass.LOOKUP,
    IntentClass.QUERY,
    IntentClass.INGEST,
    IntentClass.REVISE,
]


def _expand_intent_classes(intent_classes: list[IntentClass] | None) -> list[IntentClass]:
    """Normalize and expand intent classes for protocol Resource.

    - None or []       -> [] (resource disabled / no intents)
    - Includes WILDCARD -> all concrete intent classes
    - Otherwise        -> original list
    """
    if not intent_classes:
        return []
    if IntentClass.WILDCARD in intent_classes:
        return list(_ALL_CONCRETE_INTENT_CLASSES)
    return intent_classes


def _to_resource(curated: CuratedResource) -> Resource:
    """Convert a CuratedResource to a protocol Resource (strip curation-specific fields)."""
    return Resource(
        resource_id=curated.resource_id,
        version=curated.version,
        intent_classes=_expand_intent_classes(curated.intent_classes),
        description=curated.description,
        semantic_description=curated.semantic_description,
        tags=curated.tags,
    )


def _ci_glob_match(value: str | None, pattern: str) -> bool:
    """Case-insensitive glob match."""
    if value is None:
        return False
    return fnmatch(value.lower(), pattern.lower())


def _matches_domain_prefix(resource: CuratedResource, domain_prefix: str) -> bool:
    return _ci_glob_match(resource.resource_id, domain_prefix)


def _matches_intent_class(resource: CuratedResource, intent_class: IntentClass) -> bool:
    if intent_class == IntentClass.WILDCARD:
        return True
    if not resource.intent_classes:
        return False
    return (
        intent_class in resource.intent_classes or IntentClass.WILDCARD in resource.intent_classes
    )


def _matches_keyword(resource: CuratedResource, keyword: str) -> bool:
    searchable_fields = [
        resource.resource_id,
        resource.description,
        resource.semantic_description,
    ]
    for field in searchable_fields:
        if _ci_glob_match(field, keyword):
            return True
    for tag in resource.tags or []:
        if _ci_glob_match(tag, keyword):
            return True
    return False


def _apply_filter(
    resources: list[CuratedResource], discover_filter: DiscoverFilter | None
) -> list[CuratedResource]:
    if discover_filter is None:
        return resources

    result = resources
    if discover_filter.domain_prefix is not None:
        result = [r for r in result if _matches_domain_prefix(r, discover_filter.domain_prefix)]
    if discover_filter.intent_class is not None:
        result = [r for r in result if _matches_intent_class(r, discover_filter.intent_class)]
    if discover_filter.keyword is not None:
        result = [r for r in result if _matches_keyword(r, discover_filter.keyword)]
    return result


class DiscoverHandler(Handler):
    """Handler for the adp.discover method.

    Reads the resource list from the manifest provider, applies optional
    filters (domainPrefix, intentClass, keyword), and returns paginated results.
    """

    def __init__(
        self,
        manifest_index: ManifestIndex,
        policy_enforcer: PolicyEnforcer,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        """Initialize the handler.

        Args:
            manifest_index: The manifest index to read resources from.
            policy_enforcer: The policy enforcer to filter accessible resources.
            page_size: Maximum number of resources per page.

        Raises:
            ValueError: If ``page_size`` is not a positive integer.
        """
        if page_size <= 0:
            raise ValueError("page_size must be a positive integer")
        self._manifest_index = manifest_index
        self._policy_enforcer = policy_enforcer
        self._page_size = page_size

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.discover"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process a discover request.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            A DiscoverResult with matching resources and optional pagination cursor.
        """
        request = DiscoverRequestParams.model_validate(params)

        all_resources = self._manifest_index.list_resources()
        role = self._policy_enforcer.resolve_role(params)
        all_resources = self._policy_enforcer.filter_accessible_resources(all_resources, role)
        filtered = _apply_filter(all_resources, request.filter)

        offset = 0
        if request.cursor is not None:
            offset = _decode_cursor(request.cursor)
            if offset > len(filtered):
                raise InvalidParamsError(f"Invalid cursor: {request.cursor!r}")

        page = filtered[offset : offset + self._page_size]

        next_cursor = None
        if offset + self._page_size < len(filtered):
            next_cursor = _encode_cursor(offset + self._page_size)

        logger.info(
            "Discover: %d total, %d filtered, returning %d (offset=%d)",
            len(all_resources),
            len(filtered),
            len(page),
            offset,
        )

        return DiscoverResult(
            resources=[_to_resource(r) for r in page],
            next_cursor=next_cursor,
        )
