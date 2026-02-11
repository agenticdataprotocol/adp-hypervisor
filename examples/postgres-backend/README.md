# PostgreSQL Backend Example

> **Common setup & prerequisites** → see [examples/README.md](../README.md)

ADP Hypervisor with a PostgreSQL backend serving an e-commerce dataset
(customers, products, orders). Demonstrates **LOOKUP** and **QUERY** intents.

## Quick Start

Start PostgreSQL:

```bash
cd examples
docker compose up -d postgres
```

Open a **new terminal** at the repository root and start the ADP server:

```bash
export PG_PASSWORD=adp_pass
uv run python -m adp_hypervisor --config examples/postgres-backend/conf
```

## Sample Data

The Docker Compose service initializes a `adp_demo` database with:

| Table       | Rows | Description            |
|:------------|:-----|:-----------------------|
| `customers` | 5    | Customer profiles      |
| `products`  | 6    | Product catalog        |
| `orders`    | 10   | Customer order records |

## Try It Out

After completing the **Initialize** step from the
[general workflow](../README.md#3-initialize-the-session), paste each request
below into the server terminal.

### Discover — List Available Resources

```json
{"jsonrpc":"2.0","id":2,"method":"adp.discover","params":{}}
```

Expected: `resources` array with three entries — `demo:customers`,
`demo:products`, and `demo:orders`.

### Describe — Inspect a Resource Contract

```json
{"jsonrpc":"2.0","id":3,"method":"adp.describe","params":{"resourceId":"demo:orders","intentClass":"QUERY"}}
```

Expected: `usageContract` listing all seven fields of the `orders` table and
the available predicate operators for each field.

### Validate — Check an Intent Before Execution

```json
{"jsonrpc":"2.0","id":4,"method":"adp.validate","params":{"resourceId":"demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["id","customer_id","total","status"],"limit":10}}}
```

Expected: `{"valid": true}` — the intent is well-formed and passes policy checks.

### Execute LOOKUP — Fetch a Customer by ID

```json
{"jsonrpc":"2.0","id":5,"method":"adp.execute","params":{"resourceId":"demo:customers","intent":{"intentClass":"LOOKUP","key":{"fieldId":"id","op":"EQ","value":1},"projections":["id","name","email","city"]}}}
```

Expected: a single result for Alice Johnson.

### Execute QUERY — Search Orders

```json
{"jsonrpc":"2.0","id":6,"method":"adp.execute","params":{"resourceId":"demo:orders","intent":{"intentClass":"QUERY","predicates":{"op":"AND","predicates":[{"fieldId":"status","op":"EQ","value":"shipped"}]},"projections":["id","customer_id","total","status"],"orderBy":[{"fieldId":"ordered_at","direction":"DESC"}],"limit":10}}}
```

Expected: all orders with `status = 'shipped'`, sorted by `ordered_at` descending.

## Cleanup

```bash
cd examples
docker compose down
```
