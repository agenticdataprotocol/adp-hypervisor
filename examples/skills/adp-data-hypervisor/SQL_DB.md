---
title: "ADP SQL Usage"
---

# SQL Backend (Progressive Disclosure)

Apply this guidance when `adp_discover()` returns `"backend:RDBMS"` in the resource's `tags`
(e.g., `demo:customers`, `demo:orders`).

**Strict enforcement:** The server will reject any request that includes fields,
predicates, or operations not listed in the usage contract returned by
`adp_describe()`. Always build your `adp_execute()` intent directly from that
contract.

## SQL Intent IR Schema (Minimal)

Use this schema as a strict template for `adp_execute()` calls:

```json
{
  "type": "object",
  "required": ["intentClass", "resourceId"],
  "properties": {
    "intentClass": { "enum": ["LOOKUP", "QUERY", "INGEST", "REVISE"] },
    "resourceId": { "type": "string", "description": "Resource in domain:alias format" },
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
      "oneOf": [
        {
          "type": "object",
          "description": "Single predicate",
          "required": ["fieldId", "op", "value"],
          "properties": {
            "fieldId": { "type": "string" },
            "op": { "enum": ["EQ", "NEQ", "GT", "GTE", "LT", "LTE", "CONTAINS", "IN", "LIKE", "ILIKE", "SIMILAR"] },
            "value": {}
          }
        },
        {
          "type": "object",
          "description": "Predicate group",
          "required": ["op", "predicates"],
          "properties": {
            "op": { "enum": ["AND", "OR", "NOT"] },
            "predicates": { "type": "array" }
          }
        }
      ]
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
- Use when you can provide the primary key (e.g., `id`).
- Requires `key` with `{"fieldId": "id", "op": "EQ", "value": ...}`.
- Use `projections` from `adp_describe()` to select specific fields.

**QUERY**
- Use `predicates` — either a single predicate or a predicate group with a logic operator.
- Supported comparison operators: `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`,
  `CONTAINS`, `IN`, `LIKE`, `ILIKE`, `SIMILAR`.
- Use `projections` from `adp_describe()` to select specific fields.
- Use `orderBy` and `limit` for sorting and pagination.

**INGEST**
- Use `payload` as an array of objects, each with field-value pairs from
  `adp_describe(intent_class="INGEST")`.

**REVISE**
- Use `predicates` to target rows and `payload` for new values.
