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
import sys
from pathlib import Path

from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.policy import RoleResolver, UserRoleConfig
from adp_hypervisor.server import ADPServer
from adp_hypervisor.transport.stdio import StdioTransport

logger = logging.getLogger(__name__)

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_VALID_TRANSPORTS = ("stdio", "http")


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
        default="INFO",
        choices=_VALID_LOG_LEVELS,
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=_VALID_TRANSPORTS,
        help="Transport type (default: stdio)",
    )
    return parser


def _configure_logging(level: str) -> None:
    """Configure root logging with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


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
        policy_path.write_text("version: '1.0.0'\n", encoding="utf-8")

    return YamlManifestProvider(
        physical_path=physical_path,
        semantic_path=semantic_path,
        policy_path=policy_path,
    )


def _create_role_resolver(config_dir: Path) -> RoleResolver:
    """Create a role resolver from a config directory.

    Loads the user-to-role mapping from ``users.yaml`` in the config
    directory. If the file does not exist, returns a resolver with
    default configuration.

    Args:
        config_dir: Path to the directory containing users.yaml.

    Returns:
        A configured RoleResolver instance.
    """
    users_path = config_dir / "users.yaml"
    if not users_path.exists():
        logger.info("No users.yaml found in %s, using default role config", config_dir)
        return RoleResolver(UserRoleConfig())

    import yaml

    try:
        raw = yaml.safe_load(users_path.read_text(encoding="utf-8"))
        config = UserRoleConfig.model_validate(raw or {})
    except (yaml.YAMLError, ValueError) as exc:
        logger.error("Failed to load %s, using default role config: %s", users_path, exc)
        return RoleResolver(UserRoleConfig())

    logger.info(
        "Loaded user-role config: %d users, default_role=%r",
        len(config.users),
        config.default_role,
    )
    return RoleResolver(config)


def main(args: list[str] | None = None) -> None:
    """Parse arguments and run the ADP server.

    Args:
        args: Command-line arguments. Defaults to sys.argv[1:].
    """
    parser = _build_parser()
    parsed = parser.parse_args(args)

    _configure_logging(parsed.log_level)

    if parsed.transport == "http":
        logger.error("HTTP transport is not yet implemented")
        sys.exit(1)

    transport = StdioTransport()
    provider = _create_yaml_provider(Path(parsed.config))
    role_resolver = _create_role_resolver(Path(parsed.config))
    server = ADPServer(manifest_provider=provider, transport=transport, role_resolver=role_resolver)

    logger.info(
        "Starting ADP Hypervisor: config=%s, transport=%s, log_level=%s",
        parsed.config,
        parsed.transport,
        parsed.log_level,
    )

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
