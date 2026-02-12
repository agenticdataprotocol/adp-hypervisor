# ADP Hypervisor Examples

End-to-end examples demonstrating ADP Hypervisor with different backends.
A shared `docker-compose.yml` manages all database infrastructure, and a
unified `conf/` directory configures every backend in one place. Each
backend sub-directory contains only initialization files (seed data,
schema scripts, sample files, etc.).

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
├── docker-compose.yml      # Backend infrastructure (Postgres, pgvector, MongoDB)
├── conf/                   # ADP manifest files (all backends)
│   ├── physical.yaml
│   ├── semantic.yaml
│   └── policy.yaml
├── postgres/               # Docker init for PostgreSQL
│   └── init/
│       └── 01-init.sql
├── pgvector/               # Docker init for pgvector
│   └── init/
│       └── 01-init.sql
├── mongodb/                # Docker init for MongoDB
│   └── init/
│       └── 01-init.js
└── posix/                  # Sample files for POSIX filesystem backend
    └── data/
        ├── products/       # Product description text files (6 files)
        └── invoices/       # Invoice text files (5 files)
```

## Available Backends

| Backend    | Service    | Init Directory |
|:-----------|:-----------|:---------------|
| PostgreSQL | `postgres` | `postgres/`    |
| pgvector   | `pgvector` | `pgvector/`    |
| MongoDB    | `mongodb`  | `mongodb/`     |
| POSIX      | —          | `posix/`       |

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

Expected: `resources` array with nine entries — `pg_demo:customers`,
`pg_demo:products`, `pg_demo:orders`, `pgvector_demo:documents`,
`mongo_demo:customers`, `mongo_demo:products`, `mongo_demo:orders`,
`posix_demo:products`, and `posix_demo:invoices`.

---

#### PostgreSQL Backend

##### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":3,"method":"adp.describe","params":{"resourceId":"pg_demo:orders","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all seven fields of the `orders` table and
the available predicate operators for each field.

##### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":4,"method":"adp.validate","params":{"resourceId":"pg_demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["id","customer_id","total","status"],"limit":10}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes policy checks.

##### Execute LOOKUP — Fetch a Customer by ID

```json
{"jsonrpc":"2.0","id":5,"method":"adp.execute","params":{"resourceId":"pg_demo:customers","intent":{"intentClass":"LOOKUP","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","name","email","city"]}}}
```

Expected: a single result for Alice Johnson.

##### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":6,"method":"adp.execute","params":{"resourceId":"pg_demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["id","customer_id","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10}}}
```

Expected: all orders with `status = 'shipped'`, sorted by `ordered_at` descending.

---

#### pgvector Backend (Vector Similarity Search)

##### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":20,"method":"adp.describe","params":{"resourceId":"pgvector_demo:documents","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all six fields of the `documents` table.
The `embedding` field (type `VECTOR`) supports the `SIMILAR` operator.

##### Execute LOOKUP — Fetch a Document by ID

```json
{"jsonrpc":"2.0","id":21,"method":"adp.execute","params":{"resourceId":"pgvector_demo:documents","intent":{"intentClass":"LOOKUP","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","title","content","category"]}}}
```

Expected: a single result for "Introduction to PostgreSQL".

##### Execute QUERY — Filter Documents by Category

```json
{"jsonrpc":"2.0","id":22,"method":"adp.execute","params":{"resourceId":"pgvector_demo:documents","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"category","op":"EQ","value":"database"}]},"projections":["id","title","category"],"limit":10}}}
```

Expected: all documents with `category = 'database'`.

##### Execute QUERY — Vector Similarity Search

```json
{"jsonrpc":"2.0","id":23,"method":"adp.execute","params":{"resourceId":"pgvector_demo:documents","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"embedding","op":"SIMILAR","value":{"text":"[0.9, 0.1, 0.05]","top":3,"distanceFunction":"COSINE"}}]},"projections":["id","title","category"],"limit":5}}}
```

Expected: the top 3 documents closest to the query vector `[0.9, 0.1, 0.05]`,
ordered by cosine distance (ascending). Database-related documents should
appear first since their embeddings are nearest to the query vector.

---

#### MongoDB Backend

##### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":7,"method":"adp.describe","params":{"resourceId":"mongo_demo:orders","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all seven fields of the `orders` collection
and the available predicate operators for each field.

##### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":8,"method":"adp.validate","params":{"resourceId":"mongo_demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["_id","customer_name","total","status"],"limit":10}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes policy checks.

##### Execute LOOKUP — Fetch a Customer by Name

```json
{"jsonrpc":"2.0","id":9,"method":"adp.execute","params":{"resourceId":"mongo_demo:customers","intent":{"intentClass":"LOOKUP","key":{"fieldId":"name","op":"EQ","value":"Alice Johnson"},"projections":["_id","name","email","city"]}}}
```

Expected: a single result for Alice Johnson.

##### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":10,"method":"adp.execute","params":{"resourceId":"mongo_demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["_id","customer_name","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10}}}
```

Expected: all orders with `status = 'shipped'`, sorted by `ordered_at` descending.

---

#### POSIX Backend (Filesystem)

The POSIX backend serves files directly from the local filesystem — no
Docker container is required.

##### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":11,"method":"adp.describe","params":{"resourceId":"posix_demo:products","intentClass":"QUERY"}}
```

Expected: `usageContract` listing the fields (`name`, `object_type`,
`content`, `content_format`) for the products directory.

##### Execute QUERY — List Product Files

```json
{"jsonrpc":"2.0","id":12,"method":"adp.execute","params":{"resourceId":"posix_demo:products","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[]},"projections":["name","object_type"]}}}
```

Expected: six file entries (one per product text file in `posix/data/products/`).

##### Execute LOOKUP — Read a Specific Product File

```json
{"jsonrpc":"2.0","id":13,"method":"adp.execute","params":{"resourceId":"posix_demo:products","intent":{"intentClass":"LOOKUP","key":{"fieldId":"file_name","op":"EQ","value":"wireless-mouse.txt"},"projections":["file_name","content","content_format"]}}}
```

Expected: file content of `wireless-mouse.txt` with `content_format: "raw"`.

##### Execute QUERY — Read a Single File's Content

```json
{"jsonrpc":"2.0","id":14,"method":"adp.execute","params":{"resourceId":"posix_demo:invoices","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[]},"projections":["name","content"]}}}
```

Expected: five invoice file entries from `posix/data/invoices/`.

##### Execute LOOKUP — Read an Invoice File

```json
{"jsonrpc":"2.0","id":15,"method":"adp.execute","params":{"resourceId":"posix_demo:invoices","intent":{"intentClass":"LOOKUP","key":{"fieldId":"file_name","op":"EQ","value":"INV-2025-001.txt"},"projections":["file_name","content"]}}}
```

Expected: content of invoice `INV-2025-001.txt` (Alice Johnson, Wireless Mouse).

### 5. Cleanup

```bash
cd examples
docker compose down
```

## Sample Data

### PostgreSQL

The `postgres/init/01-init.sql` script creates an `adp_demo` database with:

| Table       | Rows | Description            |
|:------------|:-----|:-----------------------|
| `customers` | 5    | Customer profiles      |
| `products`  | 6    | Product catalog        |
| `orders`    | 10   | Customer order records |

### pgvector

The `pgvector/init/01-init.sql` script creates an `adp_demo_vector` database
with the `vector` extension and:

| Table       | Rows | Description                              |
|:------------|:-----|:-----------------------------------------|
| `documents` | 8    | Documents with 3-dimensional embeddings  |

### MongoDB

The `mongodb/init/01-init.js` script creates an `adp_demo` database with:

| Collection  | Documents | Description            |
|:------------|:----------|:-----------------------|
| `customers` | 5         | Customer profiles      |
| `products`  | 6         | Product catalog        |
| `orders`    | 10        | Customer order records |

### POSIX

The `posix/data/` directory contains plain text files for the filesystem backend:

| Directory   | Files | Description                                   |
|:------------|:------|:----------------------------------------------|
| `products/` | 6     | Product descriptions (matching the DB catalog) |
| `invoices/` | 5     | Sample invoices for customer orders            |
