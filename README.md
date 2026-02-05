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

## Development

### Running Tests

```bash
uv run pytest
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
├── pyproject.toml          # Project configuration
├── src/adp_hypervisor/     # Main hypervisor package
├── src/backends/           # Backend implementations
└── tests/                  # Test suite
```

## License

Apache-2.0

