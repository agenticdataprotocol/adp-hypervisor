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
    server = ADPServer(config_dir=parsed.config, transport=transport)

    logger.info(
        "Starting ADP Hypervisor: config=%s, transport=%s, log_level=%s",
        parsed.config,
        parsed.transport,
        parsed.log_level,
    )

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
