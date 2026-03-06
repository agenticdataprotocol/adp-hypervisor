# ADP Hypervisor Examples

End-to-end examples demonstrating ADP Hypervisor with different backends.
A shared `docker-compose.yml` manages all backend infrastructure, and a
unified `conf/` directory configures every backend in one place. Each
backend sub-directory contains only Docker initialization files (seed data,
schema scripts, etc.).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose

Install project dependencies (run once from the repository root):

```bash
uv sync
```

## Directory Layout

```
examples/
├── docker-compose.yml      # Backend infrastructure (Postgres, …)
├── conf/                   # ADP manifest files (all backends)
│   ├── physical.yaml
│   ├── semantic.yaml
│   ├── policy.yaml
│   └── users.yaml
├── data/                   # Blob storage data (LocalFS backend)
│   └── documents/
├── postgres/               # Docker init for PostgreSQL
│   └── init/
│       ├── 01-init.sql     # e-commerce schema + seed data
│       └── 02-user-roles.sql  # Gravitino release roles
└── skills/
    └── adp-data-hypervisor/  # Agent skill for Copilot / Goose
```

## Available Backends

| Backend         | Service    | Status         | Init Directory |
|:----------------|:-----------|:---------------|:---------------|
| PostgreSQL      | `postgres` | ✅ Implemented  | `postgres/`    |
| LocalFS (Blobs) | —          | ✅ Implemented  | `data/`        |

## Quick Start

### 1. Start Backend Infrastructure

```bash
cd examples
docker compose up -d
```

### 2. Start the ADP Server

Open a **new terminal** at the repository root:

```bash
export PG_PASSWORD=adp_pass
uv run python -m adp_hypervisor --config examples/conf
```

The server listens on **stdin** for JSON-RPC requests and writes responses
to stdout. Keep this terminal open.

### 3. Initialize the Session

Paste the following into the server terminal to perform the ADP handshake:

```json
{"jsonrpc":"2.0","id":1,"method":"adp.initialize","params":{"protocolVersion":"2026-01-20","capabilities":{},"clientInfo":{"name":"example-client","version":"1.0.0"}}}
```

Expected: the response contains `serverInfo` with `name: "adp-hypervisor"` and
`capabilities` listing supported intent classes.

### 4. Explore and Execute

#### Discover — List Available Resources

```json
{"jsonrpc":"2.0","id":2,"method":"adp.discover","params":{}}
```

Expected: `resources` array with five entries — `demo:customers`,
`demo:products`, `demo:orders`, `demo:documents`, and
`release.gravitino:roles`. Each resource includes a `tags` field
containing `"backend:RDBMS"` or `"backend:BLOB_STORAGE"` to indicate
the underlying backend type.

#### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":3,"method":"adp.describe","params":{"resourceId":"demo:orders","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all seven fields of the `orders` table and
the available predicate operators for each field.

#### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":4,"method":"adp.validate","params":{"resourceId":"demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"limit":10}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes validation.

#### Execute LOOKUP — Fetch a Customer by ID

```json
{"jsonrpc":"2.0","id":5,"method":"adp.execute","params":{"resourceId":"demo:customers","intent":{"intentClass":"LOOKUP","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","name","email","city"]}}}
```

Expected: a single result for Alice Johnson.

#### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":6,"method":"adp.execute","params":{"resourceId":"demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10}}}
```

Expected: all orders with `status = 'shipped'` and `total > 20`, sorted by
`ordered_at` descending.

### 5. Cleanup

```bash
cd examples
docker compose down
```

## Sample Data (PostgreSQL)

The `postgres/init/` scripts create an `adp_demo` database with:

| Table        | Rows | Description                     |
|:-------------|:-----|:--------------------------------|
| `customers`  | 5    | Customer profiles               |
| `products`   | 6    | Product catalog                 |
| `orders`     | 10   | Customer order records          |
| `user_roles` | 6    | Gravitino release role assignments |

## Agent Skill (Copilot / Goose)

The `skills/adp-data-hypervisor/` directory contains a reusable agent
skill that teaches Copilot CLI and Goose how to interact with ADP
Hypervisor resources via the `adp_mcp` MCP bridge.

To use the skill in **VS Code Copilot**, add the following to your
`.vscode/settings.json` (create the file if it doesn't exist):

```json
{
  "chat.agentSkillsLocations": ["examples/skills"]
}
```

The skill is then available as `/adp-data-hypervisor` in the Copilot
Chat panel and is automatically loaded when you ask about ADP resources.
