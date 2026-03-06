---
name: "adp-data-hypervisor"
description: "Query and manage data through the ADP (Agentic Data Protocol) Hypervisor using MCP tools. Use when asked to look up, query, insert, or update data managed by ADP resources — e.g. customers, orders, products. Provides four tools: adp_discover (list resources), adp_describe (get schema), adp_validate (check intent), adp_execute (run intent). Triggers include: data queries, record lookups, exploring available datasets, inserting or updating records."
---

# ADP Data Hypervisor

## Workflow

1. `adp_discover()` → list available resources
2. `adp_describe(resource_id, intent_class)` → get the usage contract (fields, operators, projections)
3. `adp_validate(intent)` (optional) → dry-run check before execution
4. `adp_execute(intent)` → execute and return results

## Intent IR Construction Rules

Build the intent object from `adp_describe()` output. Never invent fields or operators.

- `resourceId`: "domain:alias" format from `adp_discover()` (e.g., `"demo:orders"`)
- `intentClass`: one of `LOOKUP`, `QUERY`, `INGEST`, `REVISE` — from `adp_discover()`
- LOOKUP requires `key`: `{"fieldId": "id", "op": "EQ", "value": 1}`
- QUERY requires `predicates` — a single predicate or a group:
  - Single: `{"fieldId": "status", "op": "EQ", "value": "shipped"}`
  - Group: `{"op": "AND", "predicates": [...]}`
- Allowed predicate operators: `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`, `CONTAINS`, `IN`, `LIKE`, `ILIKE`, `SIMILAR`

## Backend-Specific Guides

`adp_discover()` injects a `"backend:<TYPE>"` tag into each resource's `tags` list.
Use it to select the right guide:
- `tags` contains `"backend:BLOB_STORAGE"` → see [BLOB_STORAGE.md](BLOB_STORAGE.md) and [BLOB_EXAMPLES.md](BLOB_EXAMPLES.md)
- `tags` contains `"backend:RDBMS"` → see [SQL_DB.md](SQL_DB.md) and [SQL_EXAMPLES.md](SQL_EXAMPLES.md)
