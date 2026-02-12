# Goose CLI + ADP Hypervisor Examples

Use [Goose CLI](https://github.com/block/goose) with ADP Hypervisor to perform
natural-language data analysis across multiple backends.

## Prerequisites

- Goose CLI installed ([installation guide](https://block.github.io/goose/docs/getting-started/installation))
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose

## Setup

### 1. Start Backend Infrastructure

```bash
cd examples
docker compose up -d
```

### 2. Install ADP MCP Extension in Goose

Add the ADP MCP bridge as an extension via `goose configure`:

```bash
goose configure
```

When prompted, select the following options:

```
◇  What would you like to configure?
│  Add Extension
│
◇  What type of extension would you like to add?
│  Command-line Extension
│
◇  What would you like to call this extension?
│  adp-mcp
│
◇  What command should be run?
│  uv --directory /path/to/adp-hypervisor-demo run python -m adp_mcp --config /path/to/adp-hypervisor-demo/examples/conf
│
◇  Please set the timeout for this tool (in secs):
│  30
│
◇  Enter a description for this extension:
│  ADP Hypervisor - unified data access across SQL, NoSQL, vector, and file backends
│
◇  Would you like to add environment variables?
│  Yes
│
◇  Environment variable name:
│  PG_PASSWORD
│
◇  Environment variable value:
│  adp_pass
│
◇  Add another environment variable?
│  No
```

> **Note:** Replace `/path/to/adp-hypervisor-demo` with the actual absolute path
> to your clone of this repository.

This is equivalent to adding the following entry in `~/.config/goose/profiles.yaml`:

```yaml
extensions:
  adp-mcp:
    type: stdio
    cmd: uv
    args:
      - --directory
      - /path/to/adp-hypervisor-demo
      - run
      - python
      - -m
      - adp_mcp
      - --config
      - /path/to/adp-hypervisor-demo/examples/conf
    env:
      PG_PASSWORD: adp_pass
```

### 3. Install the ADP Skill

Copy the skill into your Goose skills directory:

```bash
cp -r examples/goose-cli/skills/adp-data-hypervisor ~/.config/goose/skills/
```

### 4. Run a Scenario

Start Goose and follow along with a scenario:

```bash
goose session

# verify the skill is loaded, ask Goose:
What skills do you have?
```

Then follow the prompts in [scenarios/q4-business-review.md](scenarios/q4-business-review.md).

## Directory Layout

```
goose-cli/
├── README.md               # This file
├── skills/
│   └── adp-data-hypervisor/ # Goose skill for ADP Hypervisor
│       ├── SKILL.md         # Main skill definition
│       ├── SQL_DB.md        # SQL backend guide
│       ├── SQL_EXAMPLES.md  # SQL query examples
│       ├── POSIX.md         # POSIX backend guide
│       └── POSIX_EXAMPLES.md # POSIX operation examples
└── scenarios/
    └── q4-business-review.md # Q4 sales review walkthrough
```

## Available Scenarios

| Scenario | Description | Backends Used |
|:---------|:------------|:--------------|
| [Q4 Business Review](scenarios/q4-business-review.md) | Quarterly sales analysis using all backends | PostgreSQL, pgvector, MongoDB, POSIX |

## Troubleshooting

### ADP server fails to start

Ensure Docker containers are running (`docker compose ps`) and that `PG_PASSWORD`
is set in the extension environment.

### Extension not found

Verify the paths in your `profiles.yaml` are absolute paths to this repository.

### Skill not loaded

Check that the skill directory contains `SKILL.md` and that Goose has loaded it
(`goose skill list`).
