# Agent Guidelines

Code conventions for AI-assisted development on `adp-hypervisor`.

- All code, comments, and Git commit messages **must** be in English.

## Python Style

- **Formatting**: Black & Ruff, 100-char line length. Run `uv run black .` and `uv run ruff check .` before committing.
- **Type checking**: `uv run mypy` with `strict = true`. All parameters and return types must be annotated. Use `str | None` and `list[str]` (not `Optional` / `List`).
- **Imports**: absolute only, no star imports. Use aliases to resolve name collisions (e.g., `from pydantic import Field as PydanticField`).
- **Docstrings**: Google-style. Required for modules, classes, and public methods. Use `Args:`, `Returns:`, `Raises:` sections.
- **Naming**: PascalCase classes, snake_case functions/files, UPPER_SNAKE_CASE constants, `_prefix` for private members.
- **Class layout**: public methods before private methods. Use `@property` for read-only accessors. Prefer `@dataclass` for plain data; Pydantic `BaseModel` for serializable models.
- **Logging**: module-level `logger = logging.getLogger(__name__)`, `%s`-style formatting, `exc_info=True` for caught exceptions.
- **Error handling**: inherit from a specific base, use `!r` in messages, chain with `raise ... from e`.
- **`__init__.py`**: define `__all__` with category comments; re-export from submodules.

## Testing

- Use **`unittest.TestCase`** (sync) and **`unittest.IsolatedAsyncioTestCase`** (async). Do not use bare pytest classes or `pytest.fixture`.
- Use `self.assert*` methods. Do not use the bare `assert` keyword.
- Naming: `test_<module>.py` → `Test<Feature>(unittest.TestCase)` → `test_<case>`.
- Use `# ===...===` separators between test classes. Place helpers (stubs, factories) at file top with `_` prefix.
- Run tests: `uv run pytest tests/`

## Git Conventions

- Issue templates: `.github/ISSUE_TEMPLATE/` (bug-report, feature-request, improvement, epic, subtask).
- PR template: `.github/PULL_REQUEST_TEMPLATE.md`.
