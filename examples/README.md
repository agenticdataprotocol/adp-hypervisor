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
│   └── policy.yaml
├── postgres/               # Docker init for PostgreSQL
│   └── init/
│       └── 01-init.sql
└── pgvector/               # Docker init for pgvector
    └── init/
        └── 01-init.sql
```

## Available Backends

| Backend    | Service    | Status        | Init Directory |
|:-----------|:-----------|:--------------|:---------------|
| PostgreSQL | `postgres` | ✅ Implemented | `postgres/`    |
| pgvector   | `pgvector` | ✅ Implemented | `pgvector/`    |

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

Expected: `resources` array with four entries — `demo:customers`,
`demo:products`, `demo:orders`, and `demo:items`.

#### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":3,"method":"adp.describe","params":{"resourceId":"demo:orders","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all seven fields of the `orders` table and
the available predicate operators for each field.

#### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":4,"method":"adp.validate","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:orders","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"limit":10}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes validation.

#### Execute LOOKUP — Fetch a Customer by ID

```json
{"jsonrpc":"2.0","id":5,"method":"adp.execute","params":{"intent":{"intentClass":"LOOKUP","resourceId":"demo:customers","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","name","email","city"]}}}
```

Expected: a single result for Alice Johnson.

#### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":6,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:orders","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10}}}
```

Expected: all orders with `status = 'shipped'` and `total > 20`, sorted by
`ordered_at` descending.

#### Execute QUERY with SIMILAR — Vector Similarity Search (pgvector)

Find items most similar to a "tech + office" query vector using cosine
distance, priced under $50, returning the top 5 results:

```json
{"jsonrpc":"2.0","id":7,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:items","predicates":{"op":"AND","predicates":[{"fieldId":"embedding","op":"SIMILAR","value":{"vector":[0.9,0.8,0.1],"top":5,"distance_function":"COSINE"}},{"fieldId":"price","op":"LT","value":50}]},"projections":["id","title","category","price"]}}}
```

Expected: items with `price < 50` ranked by cosine similarity to
`[0.9, 0.8, 0.1]`. Electronics like "Wireless Mouse" and "USB-C Hub"
should rank highest.

#### Similarity Search with Filter — Combine Vector and Scalar Predicates

Find items similar to a "home + office" vector, but only in the "Furniture"
category:

```json
{"jsonrpc":"2.0","id":8,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:items","predicates":{"op":"AND","predicates":[{"fieldId":"embedding","op":"SIMILAR","value":{"vector":[0.1,0.7,0.9],"top":3,"distance_function":"COSINE"}},{"fieldId":"category","op":"EQ","value":"Furniture"}]},"projections":["id","title","category","price"]}}}
```

Expected: only Furniture items (Desk Lamp, Standing Desk Mat, Ergonomic
Chair Cushion), ranked by similarity to the query vector.

### 5. Cleanup

```bash
cd examples
docker compose down
```

## Sample Data (PostgreSQL)

The `postgres/init/01-init.sql` script creates an `adp_demo` database with:

| Table       | Rows | Description            |
|:------------|:-----|:-----------------------|
| `customers` | 5    | Customer profiles      |
| `products`  | 6    | Product catalog        |
| `orders`    | 10   | Customer order records |

## Sample Data (pgvector)

The `pgvector/init/01-init.sql` script creates an `adp_vector_demo` database
with the `vector` extension enabled:

| Table   | Rows | Description                                              |
|:--------|:-----|:---------------------------------------------------------|
| `items` | 10   | Product catalog with 3-D embeddings `[tech, office, home]` |

Each item has a 3-dimensional embedding vector that encodes a simplified
semantic representation. Real-world embeddings would come from a model
like `text-embedding-3-small` and have hundreds of dimensions.
