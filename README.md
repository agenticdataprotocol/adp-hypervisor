# ADP Hypervisor

A server implementation of the ADP (Agentic Data Protocol) that enables AI Agents to safely access heterogeneous data systems through a unified Intent-based interface.

## Features

- **Intent-based Data Access**: Express data operations as high-level intents (LOOKUP, QUERY, INGEST, REVISE) instead of raw queries
- **Heterogeneous Data Sources**: Unified interface to access relational databases, vector stores, and more
- **Contract-driven Interaction**: Discover available resources, describe usage contracts, validate before execute
- **Extensible Architecture**: Pluggable backends and manifest providers for easy customization


## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

## Installation

### Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/agenticdataprotocol/adp-hypervisor.git
cd adp-hypervisor

# Install dependencies
uv sync

# Install with development dependencies
uv sync --all-extras
```

### Using pip

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Prepare Manifest Files

Create a configuration directory with three YAML manifest files:

```bash
mkdir -p my-config
cp conf/physical.yaml.template my-config/physical.yaml
cp conf/semantic.yaml.template my-config/semantic.yaml
cp conf/policy.yaml.template my-config/policy.yaml
```

Edit each file to configure your backends, resources, and policies. See the templates in `conf/` for detailed examples,
or jump straight to the [examples](examples/) directory for a ready-to-run demo.

### 2. Start the Server

```bash
python -m adp_hypervisor --config my-config
```

The server starts in stdio mode, reading JSON-RPC requests from stdin and writing responses to stdout.

### CLI Usage

```
python -m adp_hypervisor --config <path> [--log-level LEVEL] [--transport TYPE]
```

| Option        | Default  | Description                                                            |
|:--------------|:---------|:-----------------------------------------------------------------------|
| `--config`    | Required | Path to manifest directory (physical.yaml, semantic.yaml, policy.yaml) |
| `--log-level` | `INFO`   | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL                   |
| `--transport` | `stdio`  | Transport type: `stdio` (HTTP planned for future release)              |

### 3. Send a Request

With the server running, send a JSON-RPC request via stdin:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"adp.initialize","params":{"protocolVersion":"2026-01-20","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | python -m adp_hypervisor --config my-config
```

### Programmatic Usage

```python
import asyncio
from adp_hypervisor import ADPServer

server = ADPServer(config_dir="my-config")
asyncio.run(server.run())
```

## Examples

The [examples](examples/) directory contains ready-to-run demos with Docker Compose
infrastructure and pre-configured manifests. See [examples/README.md](examples/README.md) for the
full walkthrough.

| Example                                              | Backend    | Description                                                                    |
|:-----------------------------------------------------|:-----------|:-------------------------------------------------------------------------------|
| [postgres-backend](examples/postgres-backend/)       | PostgreSQL | E-commerce dataset (customers, products, orders) with LOOKUP and QUERY intents |

## Development

### Running Tests

```bash
# Unit tests
uv run python -m unittest discover -s tests/unit -t tests -v

# Integration tests (requires Docker for testcontainers)
uv run python -m unittest discover -s tests/integration -v

# All tests
uv run python -m unittest discover -s tests -t tests -v
```

### Code Formatting

```bash
uv run black .
```

### Linting

```bash
uv run ruff check .
```

### Type Checking

```bash
uv run mypy src/
```

## Project Structure

```
adp-hypervisor/
├── pyproject.toml              # Project configuration
├── conf/                       # Manifest templates
├── examples/                   # Ready-to-run demos (Docker + manifests)
├── src/adp_hypervisor/         # Main hypervisor package
│   ├── server.py               # ADPServer main class
│   ├── __main__.py             # CLI entry point
│   ├── transport/              # Transport layer (stdio, HTTP)
│   ├── protocol/               # JSON-RPC types, errors, dispatcher
│   ├── handlers/               # ADP method handlers
│   └── manifest/               # Manifest models and providers
├── src/backends/               # Backend implementations (RDBMS, etc.)
└── tests/                      # Test suite
    ├── unit/                   # Unit tests
    └── integration/            # Integration & E2E tests
```

## License

Apache-2.0

