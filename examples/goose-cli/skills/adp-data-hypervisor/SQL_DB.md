---
title: "ADP SQL Usage"
---

# SQL Backend (Progressive Disclosure)

Only apply this guidance **after** `adp_describe()` indicates a SQL resource
(e.g., `pg_demo`, `mongo_demo`, `pgvector_demo`).

**Strict enforcement:** The server will reject any request that includes fields,
predicates, or operations not listed in the usage contract returned by
`adp_describe()`. Always build your `adp_execute()` intent directly from that
contract.

## SQL Intent IR Schema (Minimal)

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
              "op": { "enum": ["EQ", "NEQ", "GT", "GTE", "LT", "LTE", "CONTAINS", "IN", "LIKE", "ILIKE", "SIMILAR"] },
              "value": {}
            }
          }
        }
      }
    },
    "projections": { "type": "array", "items": { "type": "string" } },
    "orderBy": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "fieldId": { "type": "string" },
          "direction": { "enum": ["ASC", "DESC"] }
        }
      }
    },
    "limit": { "type": "integer" },
    "payload": { "type": "array", "items": { "type": "object" } }
  },
  "additionalProperties": false
}
```

## Intent-Specific Guidance

**LOOKUP**
- Use when you can provide the primary key (e.g., `id`, `_id`).
- Requires `key` with `{"fieldId": "...", "op": "EQ", "value": ...}`.

**QUERY**
- Use `predicates` with strict operator enum: `EQ`, `NEQ`, `GT`, `GTE`, `LT`,
  `LTE`, `CONTAINS`, `IN`, `LIKE`, `ILIKE`, `SIMILAR`.
- Use `projections` from `adp_describe()` to select specific fields.
- Use `orderBy` and `limit` for sorting and pagination.

**INGEST**
- Use `payload` as an array of objects, each with field-value pairs from
  `adp_describe(intent_class="INGEST")`.

**REVISE**
- Use `predicates` to target rows and `payload` for new values.

## pgvector — Vector Similarity Search

For resources with vector embedding fields (e.g., `pgvector_demo:feedback`):
- Use the `SIMILAR` operator with the embedding field.
- The `value` should be a text query string; the server handles vectorization.
- Example predicate: `{"fieldId": "embedding", "op": "SIMILAR", "value": "comfortable wireless mouse"}`
