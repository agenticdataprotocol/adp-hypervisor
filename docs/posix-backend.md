# POSIX Backend

The POSIX backend provides ADP Intent-based access to POSIX-compliant filesystems (Linux, macOS, BSD, etc.). It treats files and directories as queryable resources with metadata fields.

## Features

- **Intent-based file operations**: Use LOOKUP, QUERY, INGEST, and REVISE intents
- **Security-first design**: Path traversal prevention, symlink protection, root path allowlist
- **Multiple content formats**: Support for raw text, base64, and URI formats
- **Function-based operations**: Rename, move, update metadata, append, delete
- **Directory operations**: List children, create directories, read file content

## Configuration

### Physical Manifest

```yaml
backends:
  - id: "local_files"
    type: "POSIX"
    config:
      type: "POSIX"
      root_paths:
        - "/data/documents"
        - "/data/reports"
      allow_symlinks: false
      ignore_patterns:
        - "*.log"
        - ".DS_Store"
        - "__pycache__"
        - "__pycache__/*"
        - "*.pyc"
        - "node_modules/*"
        - ".git/*"
    metadata:
      description: "Local document storage"
```

### Configuration Options

- **root_paths** (required): List of allowed root directory paths
- **allow_symlinks** (optional, default: false): Whether to allow symlink traversal (NOT RECOMMENDED for security)
- **ignore_patterns** (optional): Gitignore-style glob patterns to exclude from operations

### Ignore Patterns

Ignore patterns use gitignore-style glob syntax to exclude files and directories from all operations:

- `*.log` - Ignores all .log files
- `.DS_Store` - Ignores macOS metadata files
- `__pycache__` - Ignores the __pycache__ directory itself
- `__pycache__/*` - Ignores contents of __pycache__ directories
- `node_modules/*` - Ignores contents of node_modules directories
- `*.pyc` - Ignores Python bytecode files

**Behavior:**
- Patterns are evaluated against the path relative to the root
- Ignored paths are filtered from directory listings
- Operations on ignored paths will fail with an error
- Patterns work recursively in subdirectories

## Source Format

The `source` parameter in intents can be specified in two formats:

1. **Relative path** (uses first root): `"documents/contract.pdf"`
2. **Explicit root** (with pipe separator): `"/data/documents|documents/contract.pdf"`

## Intent Operations

### Intent Support Matrix

| Resource Type | LOOKUP | QUERY | INGEST | REVISE |
|---------------|--------|-------|--------|--------|
| directory     | ✓ (read file) | ✓ (list) | ✓ (create file) | ✗ |
| file          | ✗ | ✓ (read) | ✓ (append) | ✓ (overwrite) |

### LOOKUP Intent

**For directories**: Reads a specific file's content within the directory. Requires `file_name` predicate to select the file.

**For files**: Not supported (use QUERY instead).

**Example - Read file content within directory**:
```python
intent = LookupIntent(
    key=IdentityPredicate(field_id="file_name", value="contract.pdf"),
    projections=["file_name", "content", "content_format"]
)
result = await backend.execute("documents", intent)
```

**Response fields**:
- `file_name`: The filename that was read
- `content`: File content
- `content_format`: Content format (raw, base64, or uri)

### QUERY Intent

For **files**: Returns file content
For **directories**: Lists children

**File query example**:
```python
# Read file as raw text
intent = QueryIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    projections=["name", "content"]
)
result = await backend.execute("documents/contract.pdf", intent)
```

**File query with base64 encoding**:
```python
intent = QueryIntent(
    predicates=PredicateGroup(
        op=LogicOperator.AND,
        predicates=[
            Predicate(field_id="content_format", op=PredicateOperator.EQ, value="base64")
        ]
    ),
    projections=["name", "content", "content_format"]
)
result = await backend.execute("documents/contract.pdf", intent)
```

**Directory query example**:
```python
intent = QueryIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    projections=["name", "object_type"],
    limit=10
)
result = await backend.execute("documents", intent)
```

**Content formats**:
- `raw` (default): UTF-8 text with error replacement
- `base64`: Base64-encoded binary data
- `uri`: File URI (e.g., `file:///path/to/file`)

### INGEST Intent

Creates new files or directories.

**Create file example**:
```python
intent = IngestIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "content": "Hello, World!",
        "content_format": "raw"
    }
)
result = await backend.execute("documents/hello.txt", intent)
```

**Create file with base64 content**:
```python
import base64

content_bytes = b"Binary data here"
content_b64 = base64.b64encode(content_bytes).decode("ascii")

intent = IngestIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "content": content_b64,
        "content_format": "base64"
    }
)
result = await backend.execute("documents/data.bin", intent)
```

**Create directory example**:
```python
intent = IngestIntent(
    predicates=PredicateGroup(
        op=LogicOperator.AND,
        predicates=[
            Predicate(field_id="object_type", op=PredicateOperator.EQ, value="directory")
        ]
    ),
    value={}
)
result = await backend.execute("documents/new_folder", intent)
```

**Overwrite existing file**:
```python
intent = IngestIntent(
    predicates=PredicateGroup(
        op=LogicOperator.AND,
        predicates=[
            Predicate(field_id="overwrite_existing", op=PredicateOperator.EQ, value=True)
        ]
    ),
    value={
        "content": "New content",
        "content_format": "raw"
    }
)
result = await backend.execute("documents/existing.txt", intent)
```

### REVISE Intent

Modifies existing files. **Note**: REVISE is only supported for files, not directories.

**Rename file**:
```python
intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "rename",
            "args": {"new_name": "contract_v2.pdf"}
        }
    }
)
result = await backend.execute("documents/contract.pdf", intent)
```

**Move file**:
```python
intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "move",
            "args": {"new_path": "archive/contract.pdf"}
        }
    }
)
result = await backend.execute("documents/contract.pdf", intent)
```

**Update file content (overwrite)**:
```python
intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "overwrite",
            "args": {}
        },
        "content": "New content",
        "content_format": "raw"
    }
)
result = await backend.execute("documents/file.txt", intent)
```

**Append to file**:
```python
intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "append",
            "args": {}
        },
        "content": "\nAppended line",
        "content_format": "raw"
    }
)
result = await backend.execute("documents/log.txt", intent)
```

**Update file metadata**:
```python
from datetime import datetime

intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "update_metadata",
            "args": {
                "mtime": datetime.now().isoformat(),
                "atime": datetime.now().isoformat()
            }
        }
    }
)
result = await backend.execute("documents/file.txt", intent)
```

**Delete file**:
```python
intent = ReviseIntent(
    predicates=PredicateGroup(op=LogicOperator.AND, predicates=[]),
    value={
        "function": {
            "name": "delete",
            "args": {}
        }
    }
)
result = await backend.execute("documents/temp.txt", intent)
```

## Security Features

### Path Validation

- **No path traversal**: Paths containing `..` are rejected
- **Root containment**: All resolved paths must be within configured root paths
- **Absolute path rejection**: Only relative paths are allowed in source parameter

### Symlink Protection

By default, symlinks are **not allowed** for security reasons:
- Root paths cannot be symlinks
- No path component can be a symlink
- Symlinks in directory listings are skipped

To enable symlinks (NOT RECOMMENDED):
```yaml
config:
  allow_symlinks: true
```

### Root Path Allowlist

Only paths under configured `root_paths` are accessible. Attempts to access other paths will fail.

## Error Handling

Common errors and their meanings:

- **"Root path not allowed"**: Source specifies a root not in `root_paths` configuration
- **"Resource path must be relative"**: Source contains an absolute path
- **"Path traversal (..) is not allowed"**: Source contains `..` components
- **"Resolved path escapes root"**: Path resolution resulted in a path outside root
- **"Symlinks are not allowed"**: Path contains a symlink and `allow_symlinks` is false
- **"Resource not found"**: File or directory does not exist
- **"Target already exists"**: INGEST without `overwrite_existing=true` on existing resource
- **"LOOKUP intent is not supported for files"**: LOOKUP can only be used on directories
- **"REVISE intent is not supported for directories"**: REVISE can only be used on files
- **"LOOKUP on directory requires 'file_name' key field_id"**: Missing file_name key field_id for directory LOOKUP

## Best Practices

1. **Use specific root paths**: Configure the minimum necessary root paths
2. **Keep symlinks disabled**: Unless absolutely necessary, keep `allow_symlinks: false`
3. **Use projections**: Request only the fields you need to reduce data transfer
4. **Handle errors gracefully**: Check for validation issues before execution
5. **Use base64 for binary**: Always use base64 encoding for binary file content
6. **Set limits**: Use `limit` parameter when listing large directories
7. **Validate paths**: Ensure paths are properly formatted before sending intents

## Limitations

1. **No wildcard queries**: Cannot query multiple files with patterns (use directory listing)
2. **No atomic operations**: Multiple operations are not transactional
3. **No file locking**: Concurrent access is not coordinated
4. **No streaming**: Large files are read entirely into memory
5. **No compression**: Content is not compressed during transfer
6. **No permissions management**: Cannot change file permissions or ownership

## Future Enhancements

Potential future improvements:

- Streaming support for large files
- Wildcard/glob pattern matching in queries
- File watching and change notifications
- Compression support for content transfer
- Atomic multi-file operations
- Permission and ownership management
- Extended attribute support
- Checksum/hash calculation
