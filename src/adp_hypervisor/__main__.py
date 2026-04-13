# Copyright 2026 Datastrato, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ADP Hypervisor CLI entry point.

Starts the ADP server with the given configuration directory,
log level, and transport type.

Usage::

    python -m adp_hypervisor --config /path/to/manifests
    python -m adp_hypervisor --config /path/to/manifests --log-level DEBUG
    python -m adp_hypervisor --config /path/to/manifests --transport stdio
"""

import argparse
import asyncio
import logging
import logging.config
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import yaml

from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.policy import UserRoleConfig, YamlRoleResolver
from adp_hypervisor.server import ADPServer
from adp_hypervisor.transport.stdio import StdioTransport

logger = logging.getLogger(__name__)

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_VALID_TRANSPORTS = ("stdio", "http")

# Built-in default logging config, matches conf/logging_conf.yaml.template.
# Used when no logging_conf.yaml is present in the config directory.
_DEFAULT_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stderr",
        },
        "file_handler": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": "./hypervisor-logs/hypervisor.log",
            "maxBytes": 10485760,
            "backupCount": 5,
            "encoding": "utf-8",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file_handler"],
    },
}


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="adp_hypervisor",
        description="ADP Hypervisor - Agentic Data Protocol server",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the manifest directory containing physical.yaml, "
        "semantic.yaml, and policy.yaml",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=_VALID_LOG_LEVELS,
        help="Override the root logging level (default: level from logging_conf.yaml or INFO)",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=_VALID_TRANSPORTS,
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Network interface to bind to (only used with --transport http, default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port to listen on (only used with --transport http, default: 8000)",
    )
    return parser


def _load_logging_config(config_dir: Path) -> dict[str, Any]:
    """Load logging configuration from config_dir/logging_conf.yaml.

    Falls back to the built-in default when the file is absent.

    Args:
        config_dir: The runtime config directory.

    Returns:
        A dict suitable for logging.config.dictConfig.
    """
    logging_conf_path = config_dir / "logging_conf.yaml"
    if logging_conf_path.exists():
        try:
            raw = yaml.safe_load(logging_conf_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            print(
                f"Warning: {logging_conf_path} is not a YAML mapping (got {type(raw).__name__}), "
                "using built-in logging defaults.",
                file=sys.stderr,
            )
        except (yaml.YAMLError, OSError):
            print(
                f"Warning: failed to parse {logging_conf_path}, using built-in logging defaults.",
                file=sys.stderr,
            )
    return _DEFAULT_LOGGING_CONFIG


def _ensure_log_directories(config: dict[str, Any]) -> None:
    """Create parent directories for all file-based log handlers.

    Scans every handler in the config dict, resolves the parent directory
    for any handler that has a ``filename`` key, and creates it if missing.
    Emits a startup notice to stderr for each resolved log file path.

    Args:
        config: The logging config dict (as passed to dictConfig).
    """
    handlers = config.get("handlers", {})
    for _name, handler_cfg in handlers.items():
        filename = handler_cfg.get("filename")
        if not filename:
            continue
        log_path = Path(filename).resolve()
        log_dir = log_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"ADP Hypervisor: logging to file {log_path}",
            file=sys.stderr,
        )


def _configure_logging(config_dir: Path, level_override: str | None) -> None:
    """Load and apply logging configuration.

    Reads logging_conf.yaml from config_dir (falls back to built-in defaults),
    ensures all file-handler directories exist, then applies the config via
    dictConfig. Overrides the root log level when --log-level is provided.

    Args:
        config_dir: The runtime config directory.
        level_override: Optional log level string (e.g. "DEBUG") from --log-level.
    """
    config = _load_logging_config(config_dir)

    if level_override is not None:
        config.setdefault("root", {})["level"] = level_override

    _ensure_log_directories(config)
    logging.config.dictConfig(config)


def _create_yaml_provider(config_dir: Path) -> YamlManifestProvider:
    """Create a YAML manifest provider from a config directory.

    Args:
        config_dir: Path to the directory containing physical.yaml,
            semantic.yaml, and policy.yaml manifest files.

    Returns:
        A configured YamlManifestProvider instance.

    Raises:
        FileNotFoundError: If required manifest files are missing.
    """
    physical_path = config_dir / "physical.yaml"
    semantic_path = config_dir / "semantic.yaml"
    policy_path = config_dir / "policy.yaml"

    for path in (physical_path, semantic_path):
        if not path.exists():
            raise FileNotFoundError(f"Manifest file not found: {path}")

    # Accept a missing policy file gracefully — ACCESS enforcement uses
    # closed-by-default semantics, so an empty policy file simply denies all.
    if not policy_path.exists():
        try:
            policy_path.write_text("version: '1.0.0'\n", encoding="utf-8")
        except OSError as exc:
            raise FileNotFoundError(
                f"Policy manifest not found at {policy_path} and could not be created. "
                "Ensure the config directory is writable or provide a policy.yaml file."
            ) from exc

    return YamlManifestProvider(
        physical_path=physical_path,
        semantic_path=semantic_path,
        policy_path=policy_path,
    )


def _create_role_resolver(config_dir: Path) -> YamlRoleResolver:
    """Create a role resolver from a config directory.

    Loads the user-to-role mapping from ``users.yaml`` in the config
    directory. If the file does not exist, returns a resolver with
    default configuration.

    Args:
        config_dir: Path to the directory containing users.yaml.

    Returns:
        A configured YamlRoleResolver instance.
    """
    users_path = config_dir / "users.yaml"
    if not users_path.exists():
        logger.info("No users.yaml found in %s, using default role config", config_dir)
        return YamlRoleResolver(UserRoleConfig())

    import yaml

    try:
        raw = yaml.safe_load(users_path.read_text(encoding="utf-8"))
        config = UserRoleConfig.model_validate(raw or {})
    except (yaml.YAMLError, ValueError) as exc:
        logger.error("Failed to load %s, using default role config: %s", users_path, exc)
        return YamlRoleResolver(UserRoleConfig())

    logger.info(
        "Loaded user-role config: %d users, default_role=%r",
        len(config.users),
        config.default_role,
    )
    return YamlRoleResolver(config)


def main(args: list[str] | None = None) -> None:
    """Parse arguments and run the ADP server.

    Args:
        args: Command-line arguments. Defaults to sys.argv[1:].
    """
    parser = _build_parser()
    parsed = parser.parse_args(args)

    config_dir = Path(parsed.config)
    _configure_logging(config_dir, parsed.log_level)

    if parsed.transport == "http":
        from adp_hypervisor.transport.base import Transport
        from adp_hypervisor.transport.http import HttpTransport

        transport: Transport = HttpTransport(host=parsed.host, port=parsed.port)
    else:
        transport = StdioTransport()

    provider = _create_yaml_provider(config_dir)
    role_resolver = _create_role_resolver(config_dir)
    server = ADPServer(
        manifest_provider=provider,
        transport=transport,
        role_resolver=role_resolver,
    )

    logger.info(
        "Starting ADP Hypervisor: config=%s, transport=%s, log_level=%s",
        parsed.config,
        parsed.transport if parsed.transport != "http" else f"http://{parsed.host}:{parsed.port}",
        parsed.log_level or "from config",
    )

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
