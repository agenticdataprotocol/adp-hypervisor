---
title: "ADP Blob Storage Examples (OpenClaw)"
---

# Blob Storage Examples

Use these examples **only after** `mcp_adp-mcp_adp_describe()` confirms a BLOB_STORAGE resource.

## 1. QUERY — List all entries

List files and directories in `demo:documents`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "QUERY",
    "resourceId": "demo:documents",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "is_directory", "op": "EQ", "value": False}]},
    "projections": ["path", "size", "content_type", "last_modified"]
  }
)
```

## 2. LOOKUP — Read a file

Read a specific file by path from `demo:documents`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "LOOKUP",
    "resourceId": "demo:documents",
    "key": {"fieldId": "path", "op": "EQ", "value": "q1-report.txt"},
    "projections": ["path", "content", "content_encoding", "size"]
  }
)
```

## 3. INGEST — Create a new file

Create a new text file in `demo:documents`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "INGEST",
    "resourceId": "demo:documents",
    "payload": [
      {
        "path": "notes/todo.txt",
        "content": "1. Review Q1 report\n2. Prepare Q2 plan",
        "content_encoding": "utf-8"
      }
    ]
  }
)
```

## 4. REVISE — Overwrite a file

Overwrite the content of an existing file:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "REVISE",
    "resourceId": "demo:documents",
    "predicates": {"fieldId": "path", "op": "EQ", "value": "q1-report.txt"},
    "payload": {
      "content": "Updated Q1 report content.\n\nRevenue: $1.5M\nGrowth: 20% QoQ",
      "content_encoding": "utf-8"
    }
  }
)
```

## 5. INGEST — Create a subdirectory

Create a new subdirectory:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "INGEST",
    "resourceId": "demo:documents",
    "payload": [
      {
        "path": "archive/2025",
        "is_directory": true
      }
    ]
  }
)
```
