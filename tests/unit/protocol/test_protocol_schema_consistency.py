"""
Verify that the Python Pydantic protocol covers and is consistent with the ADP protocol schema.

Schema is the single source of truth (schema/adp-protocol-{version}.json). These tests ensure:
- Coverage: every schema $defs type (except excluded) has a Python type
- Enum consistency: schema enum values match Python StrEnum members
- Required fields and property existence: object types have matching required/optional fields
"""

import json
from enum import StrEnum
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from adp_hypervisor import protocol
from adp_hypervisor.protocol import (
    LATEST_PROTOCOL_VERSION,
    Capabilities,
    ClientCapabilities,
    DescribeResult,
    ExecuteResult,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    IntentClass,
    UsageContract,
)

# Schema path: schema/adp-protocol-{version}.json at project root
# (version from LATEST_PROTOCOL_VERSION)
_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schema"
SCHEMA_PATH = _SCHEMA_DIR / f"adp-protocol-{LATEST_PROTOCOL_VERSION}.json"

# Schema $defs keys that do not require a Python type (generic or alias-only in schema)
SCHEMA_DEFS_EXCLUDED = {"Request", "Record<string,unknown>"}

# Map schema type name -> Python type name (when different)
# EmptyResult in schema is $ref to Result; Python exposes both EmptyResult and Result
SCHEMA_TO_PYTHON_NAME = {"EmptyResult": "Result"}


# -----------------------------------------------------------------------------
# Test class: public test methods, private helpers
# -----------------------------------------------------------------------------


class TestProtocolSchemaConsistency:
    """
    Verify protocol types and the versioned ADP protocol schema are in sync.

    Public methods (test_*) are the test cases. Private methods (_*) are
    helpers used only within this class.
    """

    # -------------------------------------------------------------------------
    # Fixture
    # -------------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def schema(self) -> dict:
        """Load schema once per class."""
        return self._load_schema()

    # -------------------------------------------------------------------------
    # Public: test methods
    # -------------------------------------------------------------------------

    def test_schema_file_exists(self) -> None:
        """Schema file exists at expected path."""
        assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    def test_protocol_coverage_every_schema_def_has_python_type(self, schema: dict) -> None:
        """
        For each schema $defs key (except excluded), protocol exposes a corresponding type.
        """
        missing = []
        for name in self._schema_def_names(schema, exclude=SCHEMA_DEFS_EXCLUDED):
            py_type = self._get_python_type(name)
            if py_type is None:
                missing.append(name)
        assert not missing, (
            f"Schema types with no Python equivalent: {missing}. "
            "Add corresponding types to adp_hypervisor.protocol or add to SCHEMA_DEFS_EXCLUDED."
        )

    def test_enum_consistency_schema_enum_matches_python_str_enum(self, schema: dict) -> None:
        """
        For each schema definition that is a string enum, the Python StrEnum
        has the same set of values.
        """
        defs = self._get_schema_defs(schema)
        for name, defn in defs.items():
            if not self._is_enum_def(defn):
                continue
            schema_values = set(defn["enum"])
            py_type = self._get_python_type(name)
            assert (
                py_type is not None
            ), f"Schema enum {name} has no Python type (coverage should have failed)"
            if not isinstance(py_type, type) or not issubclass(py_type, StrEnum):
                continue
            py_values = {m.value for m in py_type}
            assert schema_values == py_values, (
                f"Enum {name}: schema has {schema_values}, Python has {py_values}. "
                f"Symdiff: {schema_values ^ py_values}"
            )

    def test_object_type_required_fields_and_properties_match_schema(self, schema: dict) -> None:
        """
        For each schema object type with properties, the Python model has
        the same required fields (by protocol name) and at least the same properties.
        """
        defs = self._get_schema_defs(schema)
        for name, defn in defs.items():
            if not self._is_object_def(defn):
                continue
            py_type = self._get_python_type(name)
            if py_type is None:
                continue
            if not isinstance(py_type, type) or not issubclass(py_type, BaseModel):
                continue

            schema_props = set(defn.get("properties", {}))
            schema_required = set(defn.get("required", []))
            py_protocol_names = self._get_protocol_field_names(py_type)

            missing_props = schema_props - py_protocol_names
            assert not missing_props, (
                f"Object type {name}: schema properties {missing_props} missing in Python model. "
                f"Protocol field names: {py_protocol_names}"
            )

            missing_required_as_props = schema_required - py_protocol_names
            assert not missing_required_as_props, (
                f"Object type {name}: schema required fields "
                f"{missing_required_as_props} missing in Python model. "
                f"Protocol field names: {py_protocol_names}"
            )

    def test_roundtrip_initialize_request_valid_against_schema(self, schema: dict) -> None:
        """Serialized InitializeRequest (minimal valid instance) validates against schema."""
        params = InitializeRequestParams(
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="0.1.0"),
            protocol_version="2026-01-20",
        )
        obj = InitializeRequest(id=1, params=params)
        payload = obj.model_dump(by_alias=True, exclude_none=True)

        ref_schema = self._schema_for_def(schema, "InitializeRequest")
        Draft202012Validator(ref_schema).validate(payload)

    def test_roundtrip_describe_result_valid_against_schema(self, schema: dict) -> None:
        """Serialized DescribeResult (minimal valid instance) validates against schema."""
        obj = DescribeResult(
            resource_id="domain:alias",
            version=1,
            intent_class=IntentClass.QUERY,
            usage_contract=UsageContract(capabilities=Capabilities(), fields=[]),
        )
        payload = obj.model_dump(by_alias=True, exclude_none=True)

        ref_schema = self._schema_for_def(schema, "DescribeResult")
        Draft202012Validator(ref_schema).validate(payload)

    def test_roundtrip_execute_result_valid_against_schema(self, schema: dict) -> None:
        """Serialized ExecuteResult (minimal valid instance) validates against schema."""
        obj = ExecuteResult(results=[])
        payload = obj.model_dump(by_alias=True, exclude_none=True)

        ref_schema = self._schema_for_def(schema, "ExecuteResult")
        Draft202012Validator(ref_schema).validate(payload)

    # -------------------------------------------------------------------------
    # Private: helpers (internal to this test class)
    # -------------------------------------------------------------------------

    def _load_schema(self) -> dict:
        """Load schema.json from project root."""
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _get_schema_defs(self, schema: dict) -> dict:
        """Return $defs from schema."""
        return schema.get("$defs", {})

    def _schema_def_names(self, schema: dict, *, exclude: set[str] | None = None) -> list[str]:
        """Return sorted list of $defs keys, excluding given names."""
        defs = self._get_schema_defs(schema)
        excl = exclude or set()
        return sorted(k for k in defs if k not in excl)

    def _get_python_type(self, schema_name: str):
        """
        Resolve schema type name to Python type from adp_hypervisor.protocol.
        Uses SCHEMA_TO_PYTHON_NAME for aliases (e.g. EmptyResult -> Result).
        """
        python_name = SCHEMA_TO_PYTHON_NAME.get(schema_name, schema_name)
        if not hasattr(protocol, python_name):
            return None
        return getattr(protocol, python_name)

    def _get_protocol_field_names(self, model) -> set[str]:
        """
        Return the set of protocol (wire) field names for a Pydantic model (camelCase).
        Uses serialization_alias, alias, or to_camel(field_name).
        """
        names = set()
        for name, info in model.model_fields.items():
            alias = getattr(info, "serialization_alias", None) or getattr(info, "alias", None)
            if alias is not None:
                names.add(alias if isinstance(alias, str) else str(alias))
            else:
                names.add(to_camel(name))
        return names

    def _get_required_protocol_fields(self, model) -> set[str]:
        """Return the set of required field names in protocol (camelCase) form."""
        required = set()
        for name, info in model.model_fields.items():
            if info.is_required():
                alias = getattr(info, "serialization_alias", None) or getattr(info, "alias", None)
                if alias is not None:
                    required.add(alias if isinstance(alias, str) else str(alias))
                else:
                    required.add(to_camel(name))
        return required

    def _is_object_def(self, defn: dict) -> bool:
        """True if schema definition is an object type with properties."""
        return defn.get("type") == "object" and "properties" in defn

    def _is_enum_def(self, defn: dict) -> bool:
        """True if schema definition is a string enum."""
        return defn.get("type") == "string" and "enum" in defn

    def _schema_for_def(self, schema: dict, type_name: str) -> dict:
        """Build a schema that validates against $defs[type_name] with $ref resolution."""
        return {
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{type_name}",
        }
