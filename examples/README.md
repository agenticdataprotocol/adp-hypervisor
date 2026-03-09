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
├── docker-compose.yml      # Backend infrastructure (Postgres, MongoDB, …)
├── conf/                   # ADP manifest files (all backends)
│   ├── physical.yaml
│   ├── semantic.yaml
│   └── policy.yaml
├── localfs/                # Sample data for the local filesystem backend
│   └── invoices/           # Resource root — invoice files per fulfilment status
│       ├── delivered/
│       │   ├── invoice-002.txt
│       │   └── invoice-004.txt
│       ├── pending/
│       │   └── invoice-005.txt
│       └── shipped/
│           ├── invoice-001.txt
│           ├── invoice-003.txt
│           └── invoice-006.txt
├── mongodb/                # Docker init for MongoDB
│   └── init/
│       └── 01-init.js
├── postgres/               # Docker init for PostgreSQL
│   └── init/
│       └── 01-init.sql
└── pgvector/               # Docker init for pgvector
    └── init/
        └── 01-init.sql
```

## Available Backends

| Backend          | Service      | Status        | Init Directory | Requires Docker |
|:-----------------|:-------------|:--------------|:---------------|:----------------|
| PostgreSQL       | `postgres`   | ✅ Implemented | `postgres/`    | Yes             |
| pgvector         | `pgvector`   | ✅ Implemented | `pgvector/`    | Yes             |
| MongoDB          | `mongodb`    | ✅ Implemented | `mongodb/`     | Yes             |
| Local Filesystem | *(built-in)* | ✅ Implemented | `localfs/`     | **No**          |

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
export MONGO_PASSWORD=adp_pass
uv run python -m adp_hypervisor --config examples/conf
```

The MongoDB service uses admin credentials only for this local demo. Use a
scoped application user instead for non-demo environments.

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

All requests below require demo auth metadata in `params._meta.authorization`.
Use `Basic dGVzdHVzZXI6` (`testuser:` in Basic Auth form), which maps to
the demo `default` role.

#### Discover — List Available Resources

```json
{"jsonrpc":"2.0","id":2,"method":"adp.discover","params":{"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `resources` array with six entries — `demo:customers`,
`demo:products`, `demo:orders`, `demo:items`, `demo:user_profiles`,
and `demo:invoices`.

#### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":3,"method":"adp.describe","params":{"resourceId":"demo:orders","intentClass":"QUERY","_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `usageContract` listing all seven fields of the `orders` table and
the available predicate operators for each field.

#### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":4,"method":"adp.validate","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:orders","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"limit":10},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes validation.

#### Execute LOOKUP — Fetch a Customer by ID

```json
{"jsonrpc":"2.0","id":5,"method":"adp.execute","params":{"intent":{"intentClass":"LOOKUP","resourceId":"demo:customers","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","name","email","city"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains a single row for Alice Johnson.

#### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":6,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:orders","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"},{"fieldId":"total","op":"GT","value":20}]},"projections":["id","customer_id","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains the four shipped orders with IDs `9`, `6`,
`3`, and `1`, sorted by `ordered_at` descending.

#### Execute LOOKUP — Fetch a MongoDB User Profile

```json
{"jsonrpc":"2.0","id":7,"method":"adp.execute","params":{"intent":{"intentClass":"LOOKUP","resourceId":"demo:user_profiles","key":{"fieldId":"user_id","op":"EQ","value":"usr_001"},"projections":["user_id","name","email","segment","status","login_count"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains a single row for Alicia Chen in the `enterprise`
segment with `login_count` `42`.

#### Execute QUERY — Search MongoDB User Profiles

Find active enterprise users with more than 20 successful logins, ordered by
their login counts:

```json
{"jsonrpc":"2.0","id":8,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:user_profiles","predicates":{"op":"AND","predicates":[{"fieldId":"segment","op":"EQ","value":"enterprise"},{"fieldId":"status","op":"EQ","value":"active"},{"fieldId":"login_count","op":"GT","value":20}]},"projections":["user_id","name","segment","status","login_count"],"orderBy":[{"fieldId":"login_count","direction":"DESC"}],"limit":3},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains Alicia Chen and Nia Patel, sorted by
`login_count` descending.

#### Execute QUERY with SIMILAR — Vector Similarity Search (pgvector)

Find items most similar to a "tech + office" query vector using cosine
distance, priced under $50, returning the top 5 results:

```json
{"jsonrpc":"2.0","id":9,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:items","predicates":{"op":"AND","predicates":[{"fieldId":"embedding","op":"SIMILAR","value":{"vector":[0.9,0.8,0.1],"top":5,"distance_function":"COSINE"}},{"fieldId":"price","op":"LT","value":50}]},"projections":["id","title","category","price"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: items with `price < 50` ranked by cosine similarity to
`[0.9, 0.8, 0.1]`: `Wireless Mouse`, `Laptop Stand`, `USB-C Hub`,
`Notebook (A5)`, and `Ballpoint Pen Pack`.

#### Similarity Search with Filter — Combine Vector and Scalar Predicates

Find items similar to a "home + office" vector, but only in the "Furniture"
category:

```json
{"jsonrpc":"2.0","id":10,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:items","predicates":{"op":"AND","predicates":[{"fieldId":"embedding","op":"SIMILAR","value":{"vector":[0.1,0.7,0.9],"top":3,"distance_function":"COSINE"}},{"fieldId":"category","op":"EQ","value":"Furniture"}]},"projections":["id","title","category","price"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: only Furniture items ranked by similarity to the query vector:
`Standing Desk Mat`, `Desk Lamp`, and `Ergonomic Chair Cushion`.

#### Execute QUERY — List Invoice Status Buckets

The `demo:invoices` resource stores order invoice files organised into
sub-directories by fulfilment status. Query the top-level entries to see
the available status buckets:

```json
{"jsonrpc":"2.0","id":11,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:invoices","predicates":{"op":"AND","predicates":[]},"projections":["path","is_directory"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains three entries — `delivered`, `pending`,
and `shipped` (all directories, `is_directory: true`).

#### Execute QUERY — List Shipped Invoices

Use a `path EQ` predicate to scope the listing to the `shipped/`
sub-directory, and sort results by path:

```json
{"jsonrpc":"2.0","id":12,"method":"adp.execute","params":{"intent":{"intentClass":"QUERY","resourceId":"demo:invoices","predicates":{"op":"AND","predicates":[{"fieldId":"path","op":"EQ","value":"shipped"}]},"projections":["path","size"],"orderBy":[{"fieldId":"path","direction":"ASC"}]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains the three shipped invoices in path order —
`shipped/invoice-001.txt` (288 B), `shipped/invoice-003.txt` (283 B),
and `shipped/invoice-006.txt` (292 B).

#### Execute LOOKUP — Read an Invoice

Fetch the full text content of invoice #001 (Alice Johnson's Wireless
Mouse order):

```json
{"jsonrpc":"2.0","id":13,"method":"adp.execute","params":{"intent":{"intentClass":"LOOKUP","resourceId":"demo:invoices","key":{"fieldId":"path","op":"EQ","value":"shipped/invoice-001.txt"},"projections":["path","content","content_encoding"]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `results` contains one row with `content_encoding: "utf-8"` and
`content` holding the invoice text (customer details, line items, total).

#### Execute INGEST — Store a New Invoice

Order #009 (Eva Martinez, 1× USB-C Hub, $45.00) has just been shipped.
Store its invoice file:

```json
{"jsonrpc":"2.0","id":14,"method":"adp.execute","params":{"intent":{"intentClass":"INGEST","resourceId":"demo:invoices","payload":[{"path":"shipped/invoice-009.txt","content":"INVOICE #009\n------------\nDate:       2025-12-18\nStatus:     SHIPPED\n\nBill To:\n  Eva Martinez\n  eva@example.com\n  New York, NY\n\nItems:\n  1 x USB-C Hub                 $45.00\n                                -------\n  Total                         $45.00\n\nThank you for shopping with us!\n","content_encoding":"utf-8"}]},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `metadata` contains `{"status": "SUCCESS", "affected": 1}`.
A subsequent QUERY on `shipped` will include `shipped/invoice-009.txt`.

#### Execute REVISE — Update an Invoice

Order #005 (Carol White's Wireless Mouse) has now been shipped. Overwrite
the invoice file to reflect the updated status:

```json
{"jsonrpc":"2.0","id":15,"method":"adp.execute","params":{"intent":{"intentClass":"REVISE","resourceId":"demo:invoices","predicates":{"op":"AND","predicates":[{"fieldId":"path","op":"EQ","value":"pending/invoice-005.txt"}]},"payload":{"content":"INVOICE #005\n------------\nDate:       2025-12-10\nStatus:     SHIPPED\n\nBill To:\n  Carol White\n  carol@example.com\n  San Francisco, CA\n\nItems:\n  1 x Wireless Mouse            $29.99\n                                -------\n  Total                         $29.99\n\nThank you for shopping with us!\n","content_encoding":"utf-8"}},"_meta":{"authorization":"Basic dGVzdHVzZXI6"}}}
```

Expected: `metadata` contains `{"status": "SUCCESS", "affected": 1}`.
A LOOKUP for `pending/invoice-005.txt` will now return the updated invoice
with `Status: SHIPPED`.

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

## Sample Data (MongoDB)

The `mongodb/init/01-init.js` script creates an `adp_mongo_demo` database and
seeds a `users` collection:

| Collection | Documents | Description |
|:-----------|:----------|:------------|
| `users`    | 5         | Application user profiles with segment, status, and login activity |

## Sample Data (Local Filesystem)

The `localfs/invoices/` directory ships with six pre-seeded invoice files
that correspond to orders from the PostgreSQL `orders` table (no Docker or
init script required). Files are organised into sub-directories by
fulfilment status, making the directory structure itself queryable:

```
invoices/
├── delivered/   invoice-002.txt  invoice-004.txt
├── pending/     invoice-005.txt
└── shipped/     invoice-001.txt  invoice-003.txt  invoice-006.txt
```

| File                          | Customer       | Product               | Total  | Status    |
|:------------------------------|:---------------|:----------------------|:-------|:----------|
| `shipped/invoice-001.txt`     | Alice Johnson  | Wireless Mouse ×1     | $29.99 | SHIPPED   |
| `delivered/invoice-002.txt`   | Alice Johnson  | Mechanical Keyboard ×1| $89.99 | DELIVERED |
| `shipped/invoice-003.txt`     | Bob Smith      | USB-C Hub ×2          | $90.00 | SHIPPED   |
| `delivered/invoice-004.txt`   | Bob Smith      | Ballpoint Pen Pack ×3 | $17.97 | DELIVERED |
| `pending/invoice-005.txt`     | Carol White    | Wireless Mouse ×1     | $29.99 | PENDING   |
| `shipped/invoice-006.txt`     | Carol White    | Notebook (A5) ×5      | $62.50 | SHIPPED   |

Convention fields injected automatically for every entry:

| Field           | Type      | Description                                    |
|:----------------|:----------|:-----------------------------------------------|
| `path`          | STRING    | Relative path from the resource source root    |
| `size`          | INTEGER   | Size in bytes (0 for directories)              |
| `last_modified` | TIMESTAMP | Last modification time (ISO 8601)              |
| `created_at`    | TIMESTAMP | Creation time (ISO 8601)                       |
| `content_type`  | STRING    | MIME type inferred from file extension         |
| `is_directory`  | BOOLEAN   | Whether the entry is a directory               |

LOOKUP results additionally include `content` (file text) and
`content_encoding` (`"utf-8"` for text files, `"base64"` for binary).
