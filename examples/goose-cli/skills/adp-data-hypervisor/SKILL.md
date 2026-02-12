---
name: "adp-data-hypervisor"
description: "Query and manage data via ADP Hypervisor using MCP tools."
---

# ADP Data Hypervisor

This skill provides access to ADP Hypervisor tools over MCP.

## Procedure

1. `adp_discover()` → list available resources
2. `adp_describe(resource_id, intent_class)` → usage contract for a resource
3. `adp_validate(resource_id, intent)` (optional) → check Intent IR before execution
4. `adp_execute(resource_id, intent)` → execute data intent

**Important:** When calling `adp_execute()`, construct the ADP Intent IR exactly as
defined by the usage contract:

- Use `resource_id` in "domain:alias" format (e.g., `pg_demo:orders`)
- Use `intentClass` (LOOKUP, QUERY, INGEST, REVISE) matching what `adp_discover()` returned
- For QUERY: use `predicates` with `{"op": "AND", "predicates": [{"fieldId": "...", "op": "...", "value": ...}]}`
- For LOOKUP: use `key` with `{"fieldId": "...", "op": "EQ", "value": ...}`
- Only use fields listed in the usage contract from `adp_describe()`
- Do **not** invent field names or operators

**Resource & intent selection:** Always take `resource_id` and `intentClass` from the
latest `adp_discover()` results. Do not invent or omit them.

**Operator enum (strict):** Use only these operators in predicates:
`EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`, `CONTAINS`, `IN`, `LIKE`, `ILIKE`, `SIMILAR`.

## Backend Guides (Progressive Disclosure)

After `adp_describe()` confirms the backend type, consult:
- **SQL backends** (PostgreSQL, MongoDB): see `SQL_DB.md` and `SQL_EXAMPLES.md`
- **POSIX backends** (filesystem): see `POSIX.md` and `POSIX_EXAMPLES.md`
- **pgvector backends** (vector search): see `SQL_DB.md` — use `SIMILAR` operator for embedding fields

## Tools

### `adp_discover`
Discover available ADP resources.
- `domain_prefix` (optional): filter by domain prefix (e.g., "pg_demo")
- `intent_class` (optional): filter by intent class
- `keyword` (optional): keyword search
- `cursor` (optional): pagination cursor

### `adp_describe`
Get usage contract for a resource.
- `resource_id` (required): resource in "domain:alias" format
- `intent_class` (required): intent class to describe
- `version` (optional): specific version
- `cursor` (optional): pagination cursor

### `adp_validate`
Validate intent IR against resource schema.
- `resource_id` (required): target resource
- `intent` (required): intent IR dict

### `adp_execute`
Execute an ADP intent.
- `resource_id` (required): target resource
- `intent` (required): intent IR dict
- `cursor` (optional): pagination cursor
