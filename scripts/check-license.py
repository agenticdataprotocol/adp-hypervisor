# Copyright 2026 Datastrato, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Check that all applicable source files contain the Apache License 2.0 header."""

import sys
from pathlib import Path

MARKER = "Copyright 2026 Datastrato, Inc."

SCAN_RULES: list[tuple[str, list[str]]] = [
    # (glob pattern, list of root directories to scan)
    ("*.py", ["src", "tests"]),
    ("*.yaml", ["conf", "examples/conf", "tests/unit/manifest/fixtures"]),
    ("*.yml", [".github/workflows"]),
    ("*.sql", ["examples"]),
    ("*.js", ["examples"]),
]

EXTRA_FILES = [
    "examples/docker-compose.yml",
    "scripts/check-license.py",
]

EXCLUDE_DIRS = {
    "node_modules",
    ".venv",
    "dist",
    "sdist",
    ".idea",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".worktrees",
}

EXCLUDE_PATHS = {
    "examples/localfs",
}


def should_exclude(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    for excl in EXCLUDE_PATHS:
        if str(path).startswith(excl):
            return True
    return False


def collect_files(project_root: Path) -> list[Path]:
    files: set[Path] = set()

    for pattern, dirs in SCAN_RULES:
        for dir_name in dirs:
            search_root = project_root / dir_name
            if not search_root.exists():
                continue
            for path in search_root.rglob(pattern):
                if path.is_file() and not should_exclude(path.relative_to(project_root)):
                    files.add(path)

    for extra in EXTRA_FILES:
        path = project_root / extra
        if path.is_file():
            files.add(path)

    return sorted(files)


def check_header(filepath: Path) -> bool:
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read(2048)
        return MARKER in content
    except (OSError, UnicodeDecodeError):
        return False


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent

    files = collect_files(project_root)
    if not files:
        print("WARNING: No files found to check.")
        return 1

    missing: list[Path] = []
    for filepath in files:
        if not check_header(filepath):
            missing.append(filepath)

    if missing:
        print(f"ERROR: {len(missing)} file(s) missing license header:\n")
        for f in missing:
            print(f"  {f.relative_to(project_root)}")
        print(f"\nChecked {len(files)} files, {len(missing)} missing header.")
        return 1

    print(f"OK: All {len(files)} files contain the license header.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
