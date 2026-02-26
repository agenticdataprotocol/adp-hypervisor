# SimilarValue vector field migration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `vector` field to `SimilarValue`, migrate backend to consume `vector` instead of `text` for vector similarity search, and validate that `text` and `vector` are mutually exclusive.

**Architecture:** The ADP protocol schema adds a `vector: list[float]` field to `SimilarValue`. The backend SQL builder switches from reading `sv.text` (a string) to `sv.vector` (a float list), formatting it as a pgvector literal `[0.1,0.2,0.3]`. Validation ensures exactly one of `text` or `vector` is set, with `text` rejected at runtime until embedding support is implemented.

**Tech Stack:** Python, Pydantic, asyncpg, pgvector, unittest

---

## Worktree

All work happens in: `/Users/mchades/copilot/adp/adp-hypervisor/.worktrees/pr-1.14`

## Task overview

1. Update protocol schema JSON
2. Update `SimilarValue` model + validation
3. Update `VectorBackend._parse_similar_value` and `_build_query_sql`
4. Update unit tests
5. Update integration tests
6. Run full checks (black, ruff, mypy, tests)

---

### Task 1: Update protocol schema JSON

**Files:**
- Modify: `schema/adp-protocol-2026-01-20.json` (SimilarValue definition around line 1253)

**Step 1: Apply schema changes**

In `$defs.SimilarValue.properties`:
1. Change `threshold.type` from `"integer"` to `"number"`
2. Add new `vector` property after `top`:
```json
"vector": {
  "description": "Pre-computed embedding vector for direct vector similarity search.",
  "type": "array",
  "items": {
    "type": "number"
  }
}
```

**Step 2: Commit**

```bash
git add schema/adp-protocol-2026-01-20.json
git commit -m "feat(schema): add vector field to SimilarValue

Add pre-computed embedding vector field and fix threshold type
from integer to number."
```

---

### Task 2: Update `SimilarValue` model with validation

**Files:**
- Modify: `src/adp_hypervisor/protocol/types.py` (lines 190–206)

**Step 1: Write the failing test**

Add to `tests/unit/protocol/test_types.py` (or create if absent):
```python
class TestSimilarValueValidation(unittest.TestCase):
    def test_vector_field_accepted(self) -> None:
        sv = SimilarValue(vector=[0.1, 0.2, 0.3], top=5)
        self.assertEqual(sv.vector, [0.1, 0.2, 0.3])

    def test_text_raises_not_supported(self) -> None:
        with self.assertRaisesRegex(ValueError, "not yet supported"):
            SimilarValue(text="hello world", top=5)

    def test_text_and_vector_both_set_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            SimilarValue(text="hello", vector=[0.1], top=5)

    def test_neither_text_nor_vector_is_allowed(self) -> None:
        sv = SimilarValue(top=5)
        self.assertIsNone(sv.text)
        self.assertIsNone(sv.vector)
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m unittest tests/unit/protocol/test_types.py -v
```

**Step 3: Update `SimilarValue` in `types.py`**

```python
class SimilarValue(ADPModel):
    """Structured value for SIMILAR operator (vector similarity search)."""

    # TODO: Support text-based similarity search once embedding strategy is decided.
    #  When implemented, the backend should convert text to a vector via an embedding
    #  model before executing the similarity query.
    text: str | None = PydanticField(
        default=None, description="Text content to search for similarity"
    )
    blob: str | None = PydanticField(
        default=None, description="Binary content as Base64 or URI reference"
    )
    vector: list[float] | None = PydanticField(
        default=None,
        description="Pre-computed embedding vector for direct vector similarity search",
    )
    top: int | None = PydanticField(default=None, description="Maximum number of results to return")
    threshold: float | None = PydanticField(
        default=None, description="Similarity threshold (0.0 to 1.0)"
    )
    distance_function: str | None = PydanticField(
        default=None,
        description="Distance function (e.g., COSINE, L2, INNER_PRODUCT)",
    )

    @model_validator(mode="after")
    def _check_text_vector_exclusivity(self) -> "SimilarValue":
        if self.text is not None and self.vector is not None:
            raise ValueError("'text' and 'vector' are mutually exclusive in SimilarValue")
        if self.text is not None:
            raise ValueError(
                "SimilarValue.text is not yet supported. "
                "Use 'vector' with a pre-computed embedding instead."
            )
        return self
```

Note: import `model_validator` from pydantic if not already imported.

**Step 4: Run test to verify it passes**

```bash
uv run python -m unittest tests/unit/protocol/test_types.py -v
```

**Step 5: Commit**

```bash
git add src/adp_hypervisor/protocol/types.py tests/unit/protocol/test_types.py
git commit -m "feat(protocol): add vector field to SimilarValue with validation

- Add vector: list[float] | None field for pre-computed embeddings
- Validate text and vector are mutually exclusive
- Reject text field with clear error until embedding support is added"
```

---

### Task 3: Update VectorBackend to consume `vector` field

**Files:**
- Modify: `src/backends/vector/backend.py` (lines 119, 190–204)

**Step 1: Update `_parse_similar_value`**

Change the validation from checking `text` to checking `vector`:

```python
@staticmethod
def _parse_similar_value(pred: Predicate) -> SimilarValue:
    """Validate and return the ``SimilarValue`` from a SIMILAR predicate."""
    if not isinstance(pred.value, SimilarValue):
        raise ValueError(
            f"SIMILAR predicate requires a SimilarValue, got {type(pred.value).__name__}"
        )
    if pred.value.vector is None:
        raise ValueError("SimilarValue.vector must be set for vector similarity search")
    return pred.value
```

**Step 2: Update `_build_query_sql` to use `vector`**

In `_build_query_sql`, change line 119 from:
```python
params.append(sv.text)
```
to:
```python
params.append(self._format_vector(sv.vector))
```

**Step 3: Add `_format_vector` helper**

```python
@staticmethod
def _format_vector(vector: list[float]) -> str:
    """Format a float list as a pgvector literal string, e.g. ``'[0.1,0.2,0.3]'``."""
    return "[" + ",".join(str(v) for v in vector) + "]"
```

**Step 4: Commit**

```bash
git add src/backends/vector/backend.py
git commit -m "feat(backends): migrate VectorBackend from text to vector field

- _parse_similar_value now validates vector instead of text
- _build_query_sql formats list[float] as pgvector literal
- Add _format_vector helper method"
```

---

### Task 4: Update unit tests

**Files:**
- Modify: `tests/unit/backends/test_vector.py` (16 occurrences of `text="[...]"`)

**Step 1: Migrate all `text=` to `vector=`**

Replace every `SimilarValue(text="[x,y,z]", ...)` with `SimilarValue(vector=[x, y, z], ...)`.

Also update `assertEqual` assertions that check params — values will remain
the same string format `"[0.1,0.2,0.3]"` since `_format_vector` produces that.

Update validation test `test_similar_value_without_text` — rename to
`test_similar_value_without_vector` and adjust: pass `SimilarValue(blob="base64data")`
and expect error about `vector must be set`.

**Step 2: Run unit tests**

```bash
uv run python -m unittest tests/unit/backends/test_vector.py -v
```

**Step 3: Commit**

```bash
git add tests/unit/backends/test_vector.py
git commit -m "test(backends): migrate vector unit tests from text to vector field"
```

---

### Task 5: Update integration tests

**Files:**
- Modify: `tests/integration/test_backend_pgvector.py` (4 occurrences of `text="[...]"`)

**Step 1: Migrate all `text=` to `vector=`**

- Line 144: `SimilarValue(text="[0.1,0.2,0.3]", top=3)` → `SimilarValue(vector=[0.1, 0.2, 0.3], top=3)`
- Line 168: `SimilarValue(text="[0.1,0.2,0.3]", top=10)` → `SimilarValue(vector=[0.1, 0.2, 0.3], top=10)`
- Line 187: `SimilarValue(text="[0.9,0.8,0.7]", ...)` → `SimilarValue(vector=[0.9, 0.8, 0.7], ...)`
- Line 205: `SimilarValue(text="[0.5,0.5,0.5]", top=1)` → `SimilarValue(vector=[0.5, 0.5, 0.5], top=1)`

**Step 2: Commit**

```bash
git add tests/integration/test_backend_pgvector.py
git commit -m "test(integration): migrate pgvector tests from text to vector field"
```

---

### Task 6: Run full checks

**Step 1: Format & lint**

```bash
uv run black .
uv run ruff check .
```

**Step 2: Type check**

```bash
uv run mypy
```

**Step 3: Run all unit tests**

```bash
uv run python -m unittest discover -s tests/unit -v
```

**Step 4: Fix any issues, then final commit if needed**

```bash
git add -A
git commit -m "chore: fix lint/type issues from vector field migration"
```
