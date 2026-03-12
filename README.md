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
uv sync --extra dev
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

| Option        | Default            | Description                                                            |
|:--------------|:-------------------|:-----------------------------------------------------------------------|
| `--config`    | Required           | Path to manifest directory (physical.yaml, semantic.yaml, policy.yaml) |
| `--log-level` | From logging config | Override root log level: DEBUG, INFO, WARNING, ERROR, CRITICAL        |
| `--transport` | `stdio`            | Transport type: `stdio` (HTTP planned for future release)              |

### Logging Configuration

Logging is configured via `logging_conf.yaml` in the config directory. The file follows
Python's standard `logging.config.dictConfig` format.

Copy the provided template to get started:

```bash
cp conf/logging_conf.yaml.template <config-dir>/logging_conf.yaml
```

**Default behaviour (used when no `logging_conf.yaml` is present):**

- Logs go to both `stderr` (console) and a rotating file at `./hypervisor-logs/hypervisor.log`
- The log directory is created automatically if it does not exist
- The resolved log file path is printed to `stderr` at startup
- Root log level: `INFO`
- File rotation: 10 MB per file, 5 backup files

**Key tunable fields in `logging_conf.yaml`:**

| Field | Default | Description |
|:------|:--------|:------------|
| `root.level` | `INFO` | Root log level (overridable with `--log-level`) |
| `handlers.file_handler.filename` | `./hypervisor-logs/hypervisor.log` | Log file path (relative to CWD) |
| `handlers.file_handler.maxBytes` | `10485760` (10 MB) | Max file size before rotation |
| `handlers.file_handler.backupCount` | `5` | Number of backup files to keep |

> **Note:** Logs must never go to `stdout` when using stdio transport — that stream is reserved for JSON-RPC responses.

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
from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from pathlib import Path

provider = YamlManifestProvider(
    physical_path=Path("my-config/physical.yaml"),
    semantic_path=Path("my-config/semantic.yaml"),
    policy_path=Path("my-config/policy.yaml"),
)
server = ADPServer(manifest_provider=provider)
asyncio.run(server.run())
```

## Examples

The [examples](examples/) directory contains a ready-to-run demo with Docker Compose
infrastructure and pre-configured manifests. See [examples/README.md](examples/README.md) for the
full walkthrough.

| Backend          | Status         | Description                                                                       |
|:-----------------|:---------------|:----------------------------------------------------------------------------------|
| PostgreSQL       | ✅ Implemented  | E-commerce dataset (customers, products, orders) with LOOKUP and QUERY intents    |
| pgvector         | ✅ Implemented  | Vector similarity search demo with embedded product catalog items                 |
| MongoDB          | ✅ Implemented  | User profile collection with LOOKUP and QUERY intents in the shared examples demo |
| Local Filesystem | ✅ Implemented  | Invoice files organised by fulfilment status; supports LOOKUP, QUERY, INGEST, REVISE (no Docker required) |

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
├── conf/                       # Manifest templates (physical, semantic, policy, logging)
├── examples/                   # Ready-to-run demo (Docker + manifests)
├── src/adp_hypervisor/         # Main hypervisor package
│   ├── server.py               # ADPServer main class
│   ├── __main__.py             # CLI entry point
│   ├── transport/              # Transport layer (stdio; HTTP planned)
│   ├── protocol/               # JSON-RPC types, errors, dispatcher
│   ├── handlers/               # ADP method handlers
│   ├── manifest/               # Manifest models and providers
│   └── policy/                 # ACCESS policy enforcement and RBAC
├── src/backends/               # Backend implementations (RDBMS, etc.)
└── tests/                      # Test suite
    ├── unit/                   # Unit tests
    └── integration/            # Integration & E2E tests
```

## License

Apache-2.0
