"""Tests for DiscoverHandler."""

import base64
import unittest
from typing import Any
from unittest.mock import MagicMock

from adp_hypervisor.handlers.discover import (
    DEFAULT_PAGE_SIZE,
    DiscoverHandler,
    _decode_cursor,
    _encode_cursor,
)
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.semantic import CuratedResource, SourceDefinition
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import InvalidParamsError


def _make_resource(
    resource_id: str,
    intent_classes: list[str] | None = None,
    description: str | None = None,
    semantic_description: str | None = None,
    tags: list[str] | None = None,
    version: int = 1,
    source_definition: SourceDefinition | dict[str, Any] | None = None,
) -> CuratedResource:
    return CuratedResource(
        resource_id=resource_id,
        # CuratedResource.intent_classes is required. For tests that conceptually
        # represent "no intent classes", we pass an empty list rather than None
        # to reflect the spec semantics (empty list = resource disabled).
        intent_classes=intent_classes or [],
        description=description,
        semantic_description=semantic_description,
        tags=tags,
        version=version,
        backend_id="test_backend",
        # CuratedResource.source_definition is required. For Discover handler tests
        # we only care about resource metadata, so we use a minimal placeholder.
        source_definition=source_definition or SourceDefinition(source="dummy"),
    )


_SAMPLE_RESOURCES = [
    _make_resource(
        resource_id="com.acme.finance:bank_failures",
        intent_classes=["QUERY"],
        description="Bank failure records from FDIC",
        semantic_description="Historical records of bank failures.",
        tags=["FINANCE", "REGULATORY"],
    ),
    _make_resource(
        resource_id="com.acme.finance:audit_events",
        intent_classes=["QUERY"],
        description="Audit events (v2 - with actor)",
        tags=["FINANCE", "AUDIT"],
        version=2,
    ),
    _make_resource(
        resource_id="com.acme.finance:universal_resource",
        intent_classes=["*"],
        description="Universal resource",
    ),
    _make_resource(
        resource_id="com.acme.finance:failure_vectors",
        intent_classes=["QUERY"],
        description="Vector embeddings of bank failure summaries",
        tags=["VECTOR"],
    ),
    _make_resource(
        resource_id="org.example.hr:employees",
        intent_classes=["LOOKUP", "QUERY", "REVISE"],
        description="Employee directory",
        tags=["HR"],
    ),
]


def _mock_manifest(resources: list[CuratedResource] | None = None) -> ManifestIndex:
    index = MagicMock(spec=ManifestIndex)
    index.list_resources.return_value = resources if resources is not None else _SAMPLE_RESOURCES
    return index


def _mock_policy_enforcer() -> PolicyEnforcer:
    enforcer = MagicMock(spec=PolicyEnforcer)
    enforcer.resolve_role.return_value = "default"
    enforcer.filter_accessible_resources.side_effect = lambda resources, role: resources
    return enforcer


def _make_params(
    domain_prefix: str | None = None,
    intent_class: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    filter_dict: dict[str, Any] = {}
    if domain_prefix is not None:
        filter_dict["domainPrefix"] = domain_prefix
    if intent_class is not None:
        filter_dict["intentClass"] = intent_class
    if keyword is not None:
        filter_dict["keyword"] = keyword
    if filter_dict:
        params["filter"] = filter_dict
    if cursor is not None:
        params["cursor"] = cursor
    return params


# =============================================================================
# Cursor Encoding/Decoding Tests
# =============================================================================


class TestCursorEncoding(unittest.TestCase):
    def test_roundtrip(self) -> None:
        self.assertEqual(_decode_cursor(_encode_cursor(0)), 0)
        self.assertEqual(_decode_cursor(_encode_cursor(100)), 100)
        self.assertEqual(_decode_cursor(_encode_cursor(999)), 999)

    def test_invalid_cursor_raises(self) -> None:
        with self.assertRaisesRegex(InvalidParamsError, "Invalid cursor"):
            _decode_cursor("not-valid-base64!!!")

    def test_non_integer_cursor_raises(self) -> None:
        bad = base64.urlsafe_b64encode(b"abc").decode()
        with self.assertRaisesRegex(InvalidParamsError, "Invalid cursor"):
            _decode_cursor(bad)

    def test_negative_cursor_raises(self) -> None:
        negative = base64.urlsafe_b64encode(b"-1").decode()
        with self.assertRaisesRegex(InvalidParamsError, "Invalid cursor"):
            _decode_cursor(negative)


# =============================================================================
# Method Name Test
# =============================================================================


class TestDiscoverHandlerMethod(unittest.TestCase):
    def test_method_name(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        self.assertEqual(handler.method, "adp.discover")


# =============================================================================
# Basic Discovery (No Filters)
# =============================================================================


class TestDiscoverHandlerNoFilters(unittest.IsolatedAsyncioTestCase):
    async def test_returns_all_resources(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 5)

    async def test_empty_manifest_returns_empty(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=[]), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"], [])

    async def test_empty_params(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle({})

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 5)

    async def test_resource_excludes_curation_fields(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        for resource in data["resources"]:
            self.assertNotIn("backendId", resource)
            self.assertNotIn("sourceDefinition", resource)

    async def test_wildcard_intent_classes_expanded(self) -> None:
        resources = [
            _make_resource("test:wildcard", intent_classes=["*"]),
        ]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(
            set(data["resources"][0]["intentClasses"]),
            {"LOOKUP", "QUERY", "INGEST", "REVISE"},
        )

    async def test_non_wildcard_intent_classes_unchanged(self) -> None:
        resources = [
            _make_resource("test:specific", intent_classes=["QUERY", "LOOKUP"]),
        ]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(set(data["resources"][0]["intentClasses"]), {"QUERY", "LOOKUP"})


# =============================================================================
# Domain Prefix Filter
# =============================================================================


class TestDiscoverHandlerDomainPrefixFilter(unittest.IsolatedAsyncioTestCase):
    async def test_exact_match(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(domain_prefix="com.acme.finance:bank_failures"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 1)
        self.assertEqual(data["resources"][0]["resourceId"], "com.acme.finance:bank_failures")

    async def test_glob_wildcard(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(domain_prefix="com.acme.finance:*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 4)
        for r in data["resources"]:
            self.assertTrue(r["resourceId"].startswith("com.acme.finance:"))

    async def test_case_insensitive(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(domain_prefix="COM.ACME.FINANCE:*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 4)

    async def test_no_match(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(domain_prefix="com.other:*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"], [])


# =============================================================================
# Intent Class Filter
# =============================================================================


class TestDiscoverHandlerIntentClassFilter(unittest.IsolatedAsyncioTestCase):
    async def test_filter_by_query(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("com.acme.finance:bank_failures", resource_ids)
        self.assertIn("com.acme.finance:failure_vectors", resource_ids)
        # universal_resource has WILDCARD, should match any intent class
        self.assertIn("com.acme.finance:universal_resource", resource_ids)

    async def test_filter_by_lookup(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(intent_class="LOOKUP"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("org.example.hr:employees", resource_ids)
        # universal_resource with WILDCARD should also match
        self.assertIn("com.acme.finance:universal_resource", resource_ids)

    async def test_wildcard_returns_all(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(intent_class="*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 5)

    async def test_resource_without_intent_classes_not_matched(self) -> None:
        # A resource with an empty intentClasses array should not match any intent filter.
        resources = [_make_resource(resource_id="test:no_intents", intent_classes=[])]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
        )
        result = await handler.handle(_make_params(intent_class="QUERY"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"], [])


# =============================================================================
# Keyword Filter
# =============================================================================


class TestDiscoverHandlerKeywordFilter(unittest.IsolatedAsyncioTestCase):
    async def test_match_description(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="*bank failure*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("com.acme.finance:bank_failures", resource_ids)

    async def test_match_resource_id(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="*employees*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 1)
        self.assertEqual(data["resources"][0]["resourceId"], "org.example.hr:employees")

    async def test_match_semantic_description(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="*historical*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("com.acme.finance:bank_failures", resource_ids)

    async def test_match_tag(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="AUDIT"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("com.acme.finance:audit_events", resource_ids)

    async def test_case_insensitive(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="*BANK FAILURE*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertIn("com.acme.finance:bank_failures", resource_ids)

    async def test_no_match(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(_make_params(keyword="*nonexistent*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"], [])


# =============================================================================
# Combined Filters (AND logic)
# =============================================================================


class TestDiscoverHandlerCombinedFilters(unittest.IsolatedAsyncioTestCase):
    async def test_domain_prefix_and_intent_class(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(
            _make_params(domain_prefix="com.acme.finance:*", intent_class="QUERY")
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        resource_ids = {r["resourceId"] for r in data["resources"]}
        self.assertNotIn("org.example.hr:employees", resource_ids)
        self.assertIn("com.acme.finance:bank_failures", resource_ids)

    async def test_all_filters(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(
            _make_params(
                domain_prefix="com.acme.finance:*",
                intent_class="QUERY",
                keyword="*vector*",
            )
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 1)
        self.assertEqual(data["resources"][0]["resourceId"], "com.acme.finance:failure_vectors")

    async def test_mutually_exclusive_filters_return_empty(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        result = await handler.handle(
            _make_params(domain_prefix="org.example.hr:*", keyword="*finance*")
        )

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(data["resources"], [])


# =============================================================================
# Pagination Tests
# =============================================================================


class TestDiscoverHandlerPagination(unittest.IsolatedAsyncioTestCase):
    async def test_no_cursor_returns_first_page(self) -> None:
        resources = [_make_resource(f"test:r{i}") for i in range(5)]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=2,
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 2)
        self.assertEqual(data["resources"][0]["resourceId"], "test:r0")
        self.assertEqual(data["resources"][1]["resourceId"], "test:r1")
        self.assertIn("nextCursor", data)

    async def test_cursor_returns_next_page(self) -> None:
        resources = [_make_resource(f"test:r{i}") for i in range(5)]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=2,
        )

        # Get first page to get cursor
        first_result = await handler.handle(_make_params())
        first_data = first_result.model_dump(by_alias=True, exclude_none=True)
        cursor = first_data["nextCursor"]

        # Get second page
        result = await handler.handle(_make_params(cursor=cursor))
        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 2)
        self.assertEqual(data["resources"][0]["resourceId"], "test:r2")
        self.assertEqual(data["resources"][1]["resourceId"], "test:r3")

    async def test_last_page_no_next_cursor(self) -> None:
        resources = [_make_resource(f"test:r{i}") for i in range(3)]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=2,
        )

        # Get first page cursor
        first_result = await handler.handle(_make_params())
        first_data = first_result.model_dump(by_alias=True, exclude_none=True)
        cursor = first_data["nextCursor"]

        # Last page should have no next_cursor
        result = await handler.handle(_make_params(cursor=cursor))
        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 1)
        self.assertNotIn("nextCursor", data)

    async def test_exact_page_boundary(self) -> None:
        resources = [_make_resource(f"test:r{i}") for i in range(4)]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=2,
        )

        # Get first page
        first_result = await handler.handle(_make_params())
        first_data = first_result.model_dump(by_alias=True, exclude_none=True)
        self.assertIn("nextCursor", first_data)

        # Get second page (exactly fills page)
        result = await handler.handle(_make_params(cursor=first_data["nextCursor"]))
        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 2)
        self.assertNotIn("nextCursor", data)

    async def test_all_fit_in_one_page(self) -> None:
        resources = [_make_resource(f"test:r{i}") for i in range(3)]
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=5,
        )
        result = await handler.handle(_make_params())

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 3)
        self.assertNotIn("nextCursor", data)

    async def test_invalid_cursor_raises(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        with self.assertRaisesRegex(InvalidParamsError, "Invalid cursor"):
            await handler.handle(_make_params(cursor="garbage!!!"))

    async def test_default_page_size(self) -> None:
        handler = DiscoverHandler(
            manifest_index=_mock_manifest(), policy_enforcer=_mock_policy_enforcer()
        )
        self.assertEqual(handler._page_size, DEFAULT_PAGE_SIZE)

    async def test_pagination_with_filter(self) -> None:
        resources = [
            _make_resource(f"com.acme:r{i}", intent_classes=["QUERY"]) for i in range(5)
        ] + [_make_resource(f"org.other:r{i}", intent_classes=["LOOKUP"]) for i in range(3)]

        handler = DiscoverHandler(
            manifest_index=_mock_manifest(resources=resources),
            policy_enforcer=_mock_policy_enforcer(),
            page_size=2,
        )
        result = await handler.handle(_make_params(domain_prefix="com.acme:*"))

        data = result.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data["resources"]), 2)
        self.assertIn("nextCursor", data)

        # Second page
        result2 = await handler.handle(
            _make_params(domain_prefix="com.acme:*", cursor=data["nextCursor"])
        )
        data2 = result2.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data2["resources"]), 2)

        # Third (last) page
        result3 = await handler.handle(
            _make_params(domain_prefix="com.acme:*", cursor=data2["nextCursor"])
        )
        data3 = result3.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(len(data3["resources"]), 1)
        self.assertNotIn("nextCursor", data3)


# =============================================================================
# Access Filtering Tests
# =============================================================================


class TestDiscoverAccessFiltering(unittest.IsolatedAsyncioTestCase):
    async def test_filters_resources_by_access(self) -> None:
        """When filter_accessible_resources returns a subset, only that subset appears."""
        enforcer = _mock_policy_enforcer()
        subset = [_SAMPLE_RESOURCES[0], _SAMPLE_RESOURCES[4]]
        enforcer.filter_accessible_resources.side_effect = lambda resources, role: subset
        handler = DiscoverHandler(manifest_index=_mock_manifest(), policy_enforcer=enforcer)

        result = await handler.handle(_make_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        resource_ids = [r["resourceId"] for r in data["resources"]]
        self.assertEqual(len(resource_ids), 2)
        self.assertIn("com.acme.finance:bank_failures", resource_ids)
        self.assertIn("org.example.hr:employees", resource_ids)

    async def test_no_accessible_resources(self) -> None:
        """When filter_accessible_resources returns empty, result has empty resources."""
        enforcer = _mock_policy_enforcer()
        enforcer.filter_accessible_resources.side_effect = lambda resources, role: []
        handler = DiscoverHandler(manifest_index=_mock_manifest(), policy_enforcer=enforcer)

        result = await handler.handle(_make_params())
        data = result.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(data["resources"], [])
