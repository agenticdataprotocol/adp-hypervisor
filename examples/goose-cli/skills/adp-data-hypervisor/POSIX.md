---
title: "ADP POSIX Usage"
---

# POSIX Backend (Progressive Disclosure)

Only apply this guidance **after** `adp_describe()` indicates a POSIX resource
(e.g., `posix_demo:products`, `posix_demo:invoices`).

**Strict enforcement:** The server will reject any request that includes fields,
predicates, or operations not listed in the usage contract returned by
`adp_describe()`. Always build your `adp_execute()` intent directly from that
contract.

## POSIX Intent IR Schema (Minimal)

Use this schema as a strict template for `adp_execute()` calls:

```json
{
  "type": "object",
  "required": ["intentClass"],
  "properties": {
    "intentClass": { "enum": ["LOOKUP", "QUERY", "INGEST", "REVISE"] },
    "key": {
      "type": "object",
      "required": ["fieldId", "op", "value"],
      "properties": {
        "fieldId": { "type": "string" },
        "op": { "const": "EQ" },
        "value": {}
      }
    },
    "predicates": {
      "type": "object",
      "required": ["op", "predicates"],
      "properties": {
        "op": { "enum": ["AND", "OR"] },
        "predicates": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["fieldId", "op", "value"],
            "properties": {
              "fieldId": { "type": "string" },
              "op": { "enum": ["EQ", "NEQ", "GT", "GTE", "LT", "LTE", "CONTAINS", "IN", "LIKE", "ILIKE"] },
              "value": {}
            }
          }
        }
      }
    },
    "projections": { "type": "array", "items": { "type": "string" } },
    "payload": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "file_name": { "type": "string" },
          "object_type": { "type": "string" },
          "content": { "type": "string" },
          "content_format": { "enum": ["raw", "base64"] }
        }
      }
    }
  },
  "additionalProperties": false
}
```

## Detect File vs Directory
- If usage contract fields include `content`, treat as **file**.
- Otherwise, treat as **directory**.

## Intent-Specific Guidance

**LOOKUP**
- Use to read a single file by its key field (e.g., `file_name`).
- Requires `key` with `{"fieldId": "file_name", "op": "EQ", "value": "..."}`.

**QUERY**
- Returns matching file entries from the resource.
- Use `projections` to select fields (e.g., `name`, `object_type`, `content`).
- Use `predicates` to filter (e.g., by `object_type` or `name`).

**INGEST**
- Use `payload` as an array of objects to create new files.
- Each object should include `name`, `content`, and `content_format`.

**REVISE**
- Use `predicates` to target files and include an `intent` dict with
  `function` for operations: `rename`, `move`, `overwrite`, `append`.
- Example function: `{"function": "append", "content": "new line", "content_format": "raw"}`
