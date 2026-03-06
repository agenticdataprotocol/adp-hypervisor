---
name: openclaw-adp-data-hypervisor
description: "Query and manage data through the ADP (Agentic Data Protocol) Hypervisor via MCP tools. Use when asked to look up, query, insert, or update data managed by ADP resources — e.g. customers, orders, products, documents. Triggers include: data queries, record lookups, exploring available datasets, inserting or updating records, file operations."
metadata: {"openclaw": {"requires": {"env": ["ADP_USERNAME"]}, "primaryEnv": "ADP_USERNAME"}}
---

# ADP Data Hypervisor (OpenClaw)

This skill connects to the **ADP Hypervisor** via the `openclaw-plugin-mcp` plugin.
Tools are registered with the `mcp_adp-mcp_` prefix.

## Setup

Ensure the following in your `~/.openclaw/openclaw.json`:

```json5
{
  "plugins": {
    "entries": {
      "openclaw-plugin-mcp": {
        "enabled": true,
        "config": {
          "servers": {
            "adp-mcp": {
              "command": "adp-mcp",
              "args": ["--config", "/path/to/adp/conf"],
              "env": {
                "ADP_USERNAME": "your-username",
                "ADP_PASSWORD": "your-password"
              },
              "trust": "trusted"
            }
          }
        }
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `mcp_adp-mcp_adp_discover` | List available ADP resources |
| `mcp_adp-mcp_adp_describe` | Get the usage contract (fields, operators, projections) |
| `mcp_adp-mcp_adp_validate` | Dry-run check before execution |
| `mcp_adp-mcp_adp_execute` | Execute an intent and return results |

## Workflow

Always follow this order:

1. **Discover** → `mcp_adp-mcp_adp_discover()` — list resources and their supported intent classes.
2. **Describe** → `mcp_adp-mcp_adp_describe(resource_id=..., intent_class=...)` — get the usage contract (fields, operators, projections). Always call this before building an intent.
3. **Validate** (optional) → `mcp_adp-mcp_adp_validate(intent={...})` — dry-run to catch errors before execution.
4. **Execute** → `mcp_adp-mcp_adp_execute(intent={...})` — run the intent and return results.

## Intent IR Construction Rules

Build the intent object from `mcp_adp-mcp_adp_describe()` output. **Never invent fields or operators.**

- `resourceId`: `"domain:alias"` format from discover (e.g., `"demo:orders"`)
- `intentClass`: one of `LOOKUP`, `QUERY`, `INGEST`, `REVISE` — from discover
- LOOKUP requires `key`: `{"fieldId": "id", "op": "EQ", "value": 1}`
- QUERY requires `predicates` — a single predicate or a group:
  - Single: `{"fieldId": "status", "op": "EQ", "value": "shipped"}`
  - Group: `{"op": "AND", "predicates": [...]}`
- Allowed predicate operators: `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`, `CONTAINS`, `IN`, `LIKE`, `ILIKE`, `SIMILAR`

## Backend-Specific Guides

`mcp_adp-mcp_adp_discover()` injects a `"backend:<TYPE>"` tag into each resource's `tags` list.
Use it to select the right guide:
- `tags` contains `"backend:BLOB_STORAGE"` → see [BLOB_STORAGE.md](BLOB_STORAGE.md) and [BLOB_EXAMPLES.md](BLOB_EXAMPLES.md)
- `tags` contains `"backend:RDBMS"` → see [SQL_DB.md](SQL_DB.md) and [SQL_EXAMPLES.md](SQL_EXAMPLES.md)
