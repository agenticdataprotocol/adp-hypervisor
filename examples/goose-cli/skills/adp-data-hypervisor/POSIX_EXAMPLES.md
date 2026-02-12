---
title: "ADP POSIX Examples"
---

# POSIX Examples

Use these examples **only after** `adp_describe()` confirms a POSIX resource.

## 1. QUERY — List product files

List files in `posix_demo:products` with selected projections:

```python
adp_execute(
  resource_id="posix_demo:products",
  intent={
    "intentClass": "QUERY",
    "projections": ["name", "object_type"],
    "limit": 20
  }
)
```

## 2. LOOKUP — Read an invoice file

Read a single invoice by file name from `posix_demo:invoices`:

```python
adp_execute(
  resource_id="posix_demo:invoices",
  intent={
    "intentClass": "LOOKUP",
    "key": {"fieldId": "file_name", "op": "EQ", "value": "INV-2025-001.txt"},
    "projections": ["name", "file_name", "content", "content_format"]
  }
)
```

## 3. INGEST — Create a report file

Create a new file in `posix_demo:products`:

```python
adp_execute(
  resource_id="posix_demo:products",
  intent={
    "intentClass": "INGEST",
    "payload": [
      {
        "name": "Q1 Report",
        "file_name": "q1-report.txt",
        "object_type": "FILE",
        "content": "Quarterly product summary for Q1 2025.",
        "content_format": "raw"
      }
    ]
  }
)
```

## 4. REVISE — Append to an invoice file

Append content to an existing file in `posix_demo:invoices`:

```python
adp_execute(
  resource_id="posix_demo:invoices",
  intent={
    "intentClass": "REVISE",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "file_name", "op": "EQ", "value": "INV-2025-001.txt"}]},
    "payload": {"function": "append", "content": "\nPayment received on 2025-06-01.", "content_format": "raw"}
  }
)
```
