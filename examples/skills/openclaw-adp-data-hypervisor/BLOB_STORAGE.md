---
title: "ADP Blob Storage Usage (OpenClaw)"
---

# Blob Storage Backend (Progressive Disclosure)

Apply this guidance when `mcp_adp-mcp_adp_discover()` returns `"backend:BLOB_STORAGE"` in the resource's `tags`
(e.g., `demo:documents`).

**Strict enforcement:** The server rejects any request with fields or operations not
in the usage contract. Always build intents from `mcp_adp-mcp_adp_describe()` output.

## Convention Fields

BLOB_STORAGE resources use convention-based metadata fields (auto-injected):

| Field | Type | Description |
|-------|------|-------------|
| `path` | STRING | Relative path from the resource root |
| `size` | INTEGER | Size in bytes (0 for directories) |
| `last_modified` | TIMESTAMP | Last modification time (ISO 8601) |
| `created_at` | TIMESTAMP | Creation time (ISO 8601) |
| `content_type` | STRING | MIME type inferred from file extension |
| `is_directory` | BOOLEAN | Whether the entry is a directory |
| `content` | BLOB | File content (text or base64-encoded binary) |
| `content_encoding` | STRING | `"utf-8"` for text, `"base64"` for binary |

## Intent-Specific Guidance

**LOOKUP**
- Read a single file by its `path`.
- Requires `key`: `{"fieldId": "path", "op": "EQ", "value": "relative/path.txt"}`.
- Returns metadata + `content` + `content_encoding`.
- Use `projections` to select which fields to return.

**QUERY**
- List entries in the resource root (or a subdirectory).
- Returns metadata rows only — **no file content**.
- Use a `path EQ <dir>` predicate to list a subdirectory.
- Use `projections`, `orderBy`, `limit` as with SQL.

**INGEST**
- Create new files or directories via `payload`.
- Each payload item must have `"path"` (required).
- For files: include `"content"` and optionally `"content_encoding"` (`"utf-8"` or `"base64"`).
- For directories: set `"is_directory": true`.
- Target must not already exist.

**REVISE**
- Overwrite an existing file's content.
- Use `predicates` with `{"fieldId": "path", "op": "EQ", "value": "..."}` to identify the file.
- Include `"content"` and optionally `"content_encoding"` in `payload`.
