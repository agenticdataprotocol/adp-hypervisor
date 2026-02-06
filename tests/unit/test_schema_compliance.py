"""Schema compliance tests — validates Python types against the ADP JSON Schema.

Downloads the authoritative ``schema.json`` (generated from the TypeScript
definitions in ``agenticdataprotocol/agenticdataprotocol``) and compares it
against the Pydantic models defined in ``adp_hypervisor.protocol``.

Validation layers
-----------------
We use 4 independent tests rather than a single comprehensive one because
``model_json_schema()`` only works for Pydantic ``BaseModel`` subclasses.
Enum types (``StrEnum``), type aliases (``str | int``), and union types
cannot produce a JSON Schema via that API, so they require separate
handling:

1. **Type completeness** — every ``$defs`` entry has a Python counterpart.
2. **Enum values** — ``StrEnum`` member values match the JSON Schema
   ``enum`` arrays.  ``model_json_schema()`` is not available on enums.
3. **Field completeness** — for ``BaseModel`` types, property names from
   ``model_json_schema()`` are compared with the JSON Schema ``properties``.
4. **Required fields** — for ``BaseModel`` types, ``required`` arrays from
   ``model_json_schema()`` are compared with the JSON Schema ``required``.

Configuration (environment variables)
-------------------------------------
* ``ADP_SCHEMA_VERSION`` — protocol version to validate against
  (default: ``LATEST_PROTOCOL_VERSION``).
* ``GITHUB_TOKEN`` — bearer token for private-repo access.

Local fallback
--------------
When network access is unavailable, place the schema file at::

    tests/fixtures/adp_schema/<version>/schema.json

For example::

    tests/fixtures/adp_schema/2026-01-20/schema.json

The local file takes precedence over remote download.

TODO: Add compliance tests for manifest schemas
------------------------------------------------
* ``physicalmanifest.json``
* ``semanticmanifest.json``
* ``policymanifest.json``
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from adp_hypervisor.protocol import jsonrpc as jsonrpc_types
from adp_hypervisor.protocol import types as protocol_types
from adp_hypervisor.protocol.types import LATEST_PROTOCOL_VERSION

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/agenticdataprotocol/"
    "agenticdataprotocol/main/schema/{version}/schema.json"
)

# Local fallback directory for schema files.
# Users can place ``<version>/schema.json`` here when network access is
# unavailable (e.g. ``tests/fixtures/adp_schema/2026-01-20/schema.json``).
_LOCAL_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "adp_schema"

# Types in schema.json that are TypeScript-internal and have no Python
# counterpart.
_KNOWN_SKIPS: set[str] = {
    "Record<string,unknown>",  # TS utility type
    "Request",  # TS internal base interface
}

# Types that are union aliases or $ref aliases in schema.json.  They exist as
# Python type aliases (not Pydantic models), so we only check their *presence*
# — property-level comparison is not applicable.
_NON_MODEL_TYPES: set[str] = {
    "Cursor",
    "EmptyResult",
    "Intent",
    "JSONRPCMessage",
    "JSONRPCResponse",
    "ProgressToken",
    "RequestId",
    "ResourceId",
    "TraceId",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_schema_version() -> str:
    """Return the ADP schema version to validate against."""
    return os.environ.get("ADP_SCHEMA_VERSION", LATEST_PROTOCOL_VERSION)


def _fetch_schema(version: str) -> dict[str, Any]:
    """Load ``schema.json`` — tries a local fallback first, then downloads.

    Resolution order:
    1. Local file at ``tests/fixtures/adp_schema/<version>/schema.json``.
    2. Remote download from the ADP repository (requires ``GITHUB_TOKEN``
       for private repos).

    If both fail the test is **failed** (not skipped) with a message
    explaining how to provide the schema file locally as a workaround.
    """
    local_path = _LOCAL_SCHEMA_DIR / version / "schema.json"

    # 1. Try local fallback
    if local_path.exists():
        return json.loads(local_path.read_text())  # type: ignore[no-any-return]

    # 2. Try remote download
    url = _SCHEMA_URL_TEMPLATE.format(version=version)
    token = os.environ.get("GITHUB_TOKEN")

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            pytest.fail(
                f"Cannot access ADP schema (HTTP {exc.code}).\n"
                f"Workaround: download schema.json manually and place it at:\n"
                f"  {local_path}\n"
                f"Or set GITHUB_TOKEN env var for private repo access.",
                pytrace=False,
            )
        raise
    except urllib.error.URLError as exc:
        pytest.fail(
            f"Network unavailable ({exc.reason}).\n"
            f"Workaround: download schema.json manually and place it at:\n"
            f"  {local_path}",
            pytrace=False,
        )
    return {}  # unreachable, keeps mypy happy


def _get_python_type(name: str) -> Any | None:
    """Resolve *name* to a Python type from the protocol modules."""
    return getattr(protocol_types, name, None) or getattr(jsonrpc_types, name, None)


def _is_pydantic_model(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


def _is_str_enum(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, StrEnum)


def _resolve_pydantic_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Return the resolved top-level definition from ``model_json_schema()``.

    For self-referencing models (e.g. ``PredicateGroup``), Pydantic emits a
    top-level ``$ref`` pointing into ``$defs``.  This helper follows the
    reference so callers always get a dict with ``properties`` / ``required``.
    """
    schema = model_cls.model_json_schema()
    ref = schema.get("$ref")
    if ref and ref.startswith("#/$defs/"):
        ref_name = ref.split("/")[-1]
        return schema.get("$defs", {}).get(ref_name, schema)  # type: ignore[no-any-return]
    return schema


def _pydantic_properties(model_cls: type[BaseModel]) -> set[str]:
    """Property names from ``model_json_schema()`` (uses aliases)."""
    return set(_resolve_pydantic_schema(model_cls).get("properties", {}).keys())


def _pydantic_required(model_cls: type[BaseModel]) -> set[str]:
    """Required property names from ``model_json_schema()``."""
    return set(_resolve_pydantic_schema(model_cls).get("required", []))


def _const_fields(definition: dict[str, Any]) -> set[str]:
    """Return property names that have a ``const`` constraint in schema.json.

    In the TypeScript schema these are required, but in the Python
    implementation they use ``Literal[value]`` with a default — semantically
    equivalent yet *not* marked as required by Pydantic.
    """
    const_names: set[str] = set()
    for prop_name, prop_schema in definition.get("properties", {}).items():
        if "const" in prop_schema:
            const_names.add(prop_name)
    return const_names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_defs() -> dict[str, Any]:
    """``$defs`` dictionary from the ADP ``schema.json``."""
    version = _get_schema_version()
    schema = _fetch_schema(version)
    return schema.get("$defs", {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSchemaCompliance:
    """Validate Python protocol types against the ADP JSON Schema."""

    # -- 1. Type completeness ------------------------------------------------

    def test_type_completeness(self, schema_defs: dict[str, Any]) -> None:
        """Every ``$defs`` entry in schema.json has a Python counterpart."""
        missing: list[str] = []
        for def_name in schema_defs:
            if def_name in _KNOWN_SKIPS:
                continue
            if _get_python_type(def_name) is None:
                missing.append(def_name)

        assert not missing, (
            f"Missing Python types for {len(missing)} schema definition(s): {missing}"
        )

    # -- 2. Enum values ------------------------------------------------------

    def test_enum_values_match(self, schema_defs: dict[str, Any]) -> None:
        """Enum values in schema.json match Python ``StrEnum`` members."""
        mismatches: list[dict[str, Any]] = []
        for def_name, definition in schema_defs.items():
            if "enum" not in definition:
                continue
            py_type = _get_python_type(def_name)
            if py_type is None or not _is_str_enum(py_type):
                continue

            schema_values = set(definition["enum"])
            python_values = {m.value for m in py_type}

            if schema_values != python_values:
                mismatches.append(
                    {
                        "type": def_name,
                        "in_schema_only": sorted(schema_values - python_values),
                        "in_python_only": sorted(python_values - schema_values),
                    }
                )

        assert not mismatches, f"Enum value mismatches:\n{json.dumps(mismatches, indent=2)}"

    # -- 3. Field completeness -----------------------------------------------

    def test_object_fields_match(self, schema_defs: dict[str, Any]) -> None:
        """Object property names in schema.json exist in Python models.

        Uses ``model_json_schema()`` to obtain the Pydantic-side property
        names (which already include aliases), then checks that every
        property declared in the authoritative schema is present.
        """
        mismatches: list[dict[str, Any]] = []
        for def_name, definition in schema_defs.items():
            if def_name in _KNOWN_SKIPS or def_name in _NON_MODEL_TYPES:
                continue
            if definition.get("type") != "object":
                continue

            py_type = _get_python_type(def_name)
            if py_type is None or not _is_pydantic_model(py_type):
                continue

            schema_props = set(definition.get("properties", {}).keys())
            pydantic_props = _pydantic_properties(py_type)

            missing_in_python = schema_props - pydantic_props
            if missing_in_python:
                mismatches.append(
                    {
                        "type": def_name,
                        "missing_in_python": sorted(missing_in_python),
                        "schema_properties": sorted(schema_props),
                        "pydantic_properties": sorted(pydantic_props),
                    }
                )

        assert not mismatches, (
            f"Field mismatches ({len(mismatches)} type(s)):\n{json.dumps(mismatches, indent=2)}"
        )

    # -- 4. Required fields --------------------------------------------------

    def test_required_fields_match(self, schema_defs: dict[str, Any]) -> None:
        """Required fields in schema.json are also required in Python models.

        Uses ``model_json_schema()`` to obtain the Pydantic-side
        ``required`` array.
        """
        mismatches: list[dict[str, Any]] = []
        for def_name, definition in schema_defs.items():
            if def_name in _KNOWN_SKIPS or def_name in _NON_MODEL_TYPES:
                continue
            if definition.get("type") != "object":
                continue

            py_type = _get_python_type(def_name)
            if py_type is None or not _is_pydantic_model(py_type):
                continue

            schema_required = set(definition.get("required", []))
            pydantic_required_fields = _pydantic_required(py_type)

            # Exclude const fields — they are required in the TS schema but
            # use Literal[value] + default in Python (semantically equivalent).
            missing_required = (
                schema_required - pydantic_required_fields - _const_fields(definition)
            )
            if missing_required:
                mismatches.append(
                    {
                        "type": def_name,
                        "required_in_schema_not_python": sorted(missing_required),
                    }
                )

        assert not mismatches, (
            f"Required-field mismatches ({len(mismatches)} type(s)):\n"
            f"{json.dumps(mismatches, indent=2)}"
        )
