# ADP Hypervisor Examples

End-to-end examples demonstrating ADP Hypervisor with different backends.
A shared `docker-compose.yml` in this directory manages all backend
infrastructure. Each sub-directory contains an example with ADP manifest
configs and a walkthrough README.

## Prerequisites

All examples require:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose

Install project dependencies (run once from the repository root):

```bash
uv sync
```

## Available Examples

| Example                               | Backend    | Description                                                                    |
|:--------------------------------------|:-----------|:-------------------------------------------------------------------------------|
| [postgres-backend](postgres-backend/) | PostgreSQL | E-commerce dataset (customers, products, orders) with LOOKUP and QUERY intents |

## General Workflow

Every example follows the same pattern:

### 1. Start the Backend Infrastructure

```bash
cd examples
docker compose up -d
```

To start only a specific service (e.g., `postgres`):

```bash
docker compose up -d postgres
```

### 2. Start the ADP Server

Open a **new terminal** at the repository root. Set any required environment
variables (see the example README), then start the server:

```bash
uv run python -m adp_hypervisor --config examples/<example-name>/conf
```

The server listens on **stdin** for JSON-RPC requests and writes responses to
stdout. Keep this terminal open.

### 3. Initialize the Session

Paste the following into the server terminal to perform the ADP handshake.
This request is **the same for every example**:

```json
{"jsonrpc":"2.0","id":1,"method":"adp.initialize","params":{"protocolVersion":"2026-01-20","capabilities":{},"clientInfo":{"name":"example-client","version":"1.0.0"}}}
```

Expected: the response contains `serverInfo` with `name: "adp-hypervisor"` and
`capabilities` listing supported intent classes.

### 4. Explore and Execute

Follow the example-specific README for the remaining operations:

- **Discover** — list available resources
- **Describe** — inspect a resource's fields and predicate capabilities
- **Validate** — check an intent before execution
- **Execute** — run LOOKUP or QUERY intents against real data

### 5. Cleanup

```bash
cd examples
docker compose down
```
