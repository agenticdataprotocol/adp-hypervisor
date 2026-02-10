"""
Verify that the Python Pydantic manifest models are consistent with the
versioned ADP manifest schemas.

Schemas are the single source of truth:
- Physical: schema/adp-physical-manifest-{version}.json
- Semantic: schema/adp-semantic-manifest-{version}.json
- Policy:   schema/adp-policy-manifest-{version}.json

These tests ensure:
- Coverage: every schema $defs type (except excluded) has a Python type
- Enum consistency: schema enum values match Python StrEnum members
- Required fields and property existence: object types have matching
  required/optional fields
"""

import json
import unittest
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from adp_hypervisor import manifest, protocol
from adp_hypervisor.manifest import (
    LATEST_MANIFEST_SCHEMA_VERSION,
    PhysicalManifest,
    PolicyManifest,
    SemanticManifest,
)

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schema"

PHYSICAL_SCHEMA_PATH = _SCHEMA_DIR / f"adp-physical-manifest-{LATEST_MANIFEST_SCHEMA_VERSION}.json"
SEMANTIC_SCHEMA_PATH = _SCHEMA_DIR / f"adp-semantic-manifest-{LATEST_MANIFEST_SCHEMA_VERSION}.json"
POLICY_SCHEMA_PATH = _SCHEMA_DIR / f"adp-policy-manifest-{LATEST_MANIFEST_SCHEMA_VERSION}.json"

# Schema $defs keys that do not require a Python type (generic or alias-only in schema).
# "Backend" is mapped to BackendDefinition in Python to avoid collision with backends.base.Backend.
SCHEMA_DEFS_EXCLUDED = {"Request", "Record<string,unknown>", "Backend"}


class TestManifestSchemaConsistency(unittest.TestCase):
    """
    Verify manifest models and the versioned ADP manifest schemas are in sync.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._physical_schema = cls._load_schema(PHYSICAL_SCHEMA_PATH)
        cls._semantic_schema = cls._load_schema(SEMANTIC_SCHEMA_PATH)
        cls._policy_schema = cls._load_schema(POLICY_SCHEMA_PATH)

    # -------------------------------------------------------------------------
    # Public: test methods
    # -------------------------------------------------------------------------

    def test_schema_files_exist(self) -> None:
        """Schema files exist at expected paths."""
        self.assertTrue(
            PHYSICAL_SCHEMA_PATH.exists(), f"Physical schema not found at {PHYSICAL_SCHEMA_PATH}"
        )
        self.assertTrue(
            SEMANTIC_SCHEMA_PATH.exists(), f"Semantic schema not found at {SEMANTIC_SCHEMA_PATH}"
        )
        self.assertTrue(
            POLICY_SCHEMA_PATH.exists(), f"Policy schema not found at {POLICY_SCHEMA_PATH}"
        )

    def test_manifest_coverage_every_schema_def_has_python_type(self) -> None:
        """
        For each schema $defs key (except excluded), a corresponding Python type exists.
        """
        missing: list[tuple[str, str]] = []
        for schema_name, schema in self._iter_schemas():
            for def_name in self._schema_def_names(schema, exclude=SCHEMA_DEFS_EXCLUDED):
                py_type = self._get_python_type(def_name)
                if py_type is None:
                    missing.append((schema_name, def_name))

        self.assertFalse(
            missing,
            (
                "Schema types with no Python equivalent: "
                f"{missing}. "
                "Add corresponding types to adp_hypervisor.manifest or adp_hypervisor.protocol "
                "or add to SCHEMA_DEFS_EXCLUDED."
            ),
        )

    def test_enum_consistency_schema_enum_matches_python_str_enum(self) -> None:
        """
        For each schema definition that is a string enum, the Python StrEnum
        has the same set of values.
        """
        for _schema_name, schema in self._iter_schemas():
            defs = self._get_schema_defs(schema)
            for name, defn in defs.items():
                if not self._is_enum_def(defn):
                    continue
                schema_values = set(defn["enum"])
                py_type = self._get_python_type(name)
                # Coverage test should already have caught missing types
                self.assertIsNotNone(
                    py_type, f"Schema enum {name} has no Python type (coverage should have failed)"
                )
                if not isinstance(py_type, type) or not issubclass(py_type, StrEnum):
                    continue
                py_values = {m.value for m in py_type}
                self.assertEqual(
                    schema_values,
                    py_values,
                    (
                        f"Enum {name}: schema has {schema_values}, Python has {py_values}. "
                        f"Symdiff: {schema_values ^ py_values}"
                    ),
                )

    def test_object_type_required_fields_and_properties_match_schema(self) -> None:
        """
        For each schema object type with properties, the Python model has
        the same required fields (by wire name) and at least the same properties.
        """
        for _schema_name, schema in self._iter_schemas():
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
                py_required = self._get_required_protocol_fields(py_type)

                missing_props = schema_props - py_protocol_names
                self.assertFalse(
                    missing_props,
                    (
                        f"Object type {name}: schema properties {missing_props} missing in Python "
                        f"model. Protocol field names: {py_protocol_names}"
                    ),
                )

                missing_required_as_props = schema_required - py_protocol_names
                self.assertFalse(
                    missing_required_as_props,
                    (
                        f"Object type {name}: schema required fields "
                        f"{missing_required_as_props} missing in Python model. "
                        f"Protocol field names: {py_protocol_names}"
                    ),
                )

                missing_required_fields = schema_required - py_required
                self.assertFalse(
                    missing_required_fields,
                    (
                        f"Object type {name}: schema required fields "
                        f"{missing_required_fields} are not required in Python model. "
                        f"Required protocol field names: {py_required}"
                    ),
                )

    def test_root_models_have_schema_versions(self) -> None:
        """
        Root manifest models should expose a version field and validate simple examples.
        """
        PhysicalManifest(version="1.0.0", backends=[])
        SemanticManifest(version="1.0.0", resources=[])
        PolicyManifest(version="1.0.0", policies=None)

    # -------------------------------------------------------------------------
    # Private: helpers (internal to this test class)
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_schema(path: Path) -> dict:
        """Load a schema JSON file."""
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _get_schema_defs(schema: dict) -> dict:
        """Return $defs from schema."""
        return schema.get("$defs", {})

    @staticmethod
    def _schema_def_names(schema: dict, *, exclude: set[str] | None = None) -> list[str]:
        """Return sorted list of $defs keys, excluding given names."""
        defs = TestManifestSchemaConsistency._get_schema_defs(schema)
        excl = exclude or set()
        return sorted(k for k in defs if k not in excl)

    @staticmethod
    def _iter_schemas():
        """Yield (name, schema_dict) for each manifest schema."""
        yield "physical", TestManifestSchemaConsistency._physical_schema
        yield "semantic", TestManifestSchemaConsistency._semantic_schema
        yield "policy", TestManifestSchemaConsistency._policy_schema

    @staticmethod
    def _get_python_type(schema_name: str):
        """
        Resolve schema type name to Python type from manifest or protocol modules.
        """
        if hasattr(manifest, schema_name):
            return getattr(manifest, schema_name)
        if hasattr(protocol, schema_name):
            return getattr(protocol, schema_name)
        return None

    @staticmethod
    def _get_protocol_field_names(model: type[BaseModel]) -> set[str]:
        """
        Return the set of protocol (wire) field names for a Pydantic model (camelCase).

        Uses serialization_alias, alias, or to_camel(field_name).
        """
        names: set[str] = set()
        for name, info in model.model_fields.items():
            alias = getattr(info, "serialization_alias", None) or getattr(info, "alias", None)
            if alias is not None:
                names.add(alias if isinstance(alias, str) else str(alias))
            else:
                names.add(to_camel(name))
        return names

    @staticmethod
    def _get_required_protocol_fields(model: type[BaseModel]) -> set[str]:
        """Return the set of required field names in protocol (camelCase) form."""
        required: set[str] = set()
        for name, info in model.model_fields.items():
            if info.is_required():
                alias = getattr(info, "serialization_alias", None) or getattr(info, "alias", None)
                if alias is not None:
                    required.add(alias if isinstance(alias, str) else str(alias))
                else:
                    required.add(to_camel(name))
        return required

    @staticmethod
    def _is_object_def(defn: dict) -> bool:
        """True if schema definition is an object type with properties."""
        return defn.get("type") == "object" and "properties" in defn

    @staticmethod
    def _is_enum_def(defn: dict) -> bool:
        """True if schema definition is a string enum."""
        return defn.get("type") == "string" and "enum" in defn
