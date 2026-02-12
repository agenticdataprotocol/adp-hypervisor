"""
ADP Hypervisor main server class.

Orchestrates the lifecycle of the ADP server by wiring together transport,
protocol dispatcher, handlers, manifest provider, and backend registry.
"""

import asyncio
import logging
import signal
from pathlib import Path

from adp_hypervisor.handlers import (
    DescribeHandler,
    DiscoverHandler,
    ExecuteHandler,
    InitializeHandler,
    PingHandler,
    ValidateHandler,
)
from adp_hypervisor.manifest.index import ManifestIndex
from adp_hypervisor.manifest.physical import BackendDefinition, BackendType
from adp_hypervisor.manifest.yaml_provider import YamlManifestProvider
from adp_hypervisor.protocol.dispatcher import Dispatcher
from adp_hypervisor.transport.base import Transport
from adp_hypervisor.transport.stdio import StdioTransport
from backends.base import Backend
from backends.registry import BackendRegistry

logger = logging.getLogger(__name__)


def _create_backend(definition: BackendDefinition) -> Backend | None:
    """Create a backend instance from a definition, using lazy imports.

    Args:
        definition: The backend definition from the physical manifest.

    Returns:
        A backend instance, or None if the backend type is not supported.
    """
    if definition.type == BackendType.RDBMS:
        from backends.rdbms.postgres import PostgresBackend

        return PostgresBackend(definition=definition)

    if definition.type == BackendType.NOSQL:
        from backends.nosql.mongodb import MongoDBBackend

        return MongoDBBackend(definition=definition)

    if definition.type == BackendType.VECTOR:
        from backends.vector.pgvector import PgVectorBackend

        return PgVectorBackend(definition=definition)

    if definition.type == BackendType.POSIX:
        from backends.posix import POSIXBackend

        return POSIXBackend(definition=definition)

    return None


class ADPServer:
    """Main ADP Hypervisor server.

    Loads manifests, initializes backends, registers handlers, and runs the
    transport message loop.
    """

    def __init__(
        self,
        config_dir: str | Path,
        transport: Transport | None = None,
    ) -> None:
        """Initialize the server.

        Args:
            config_dir: Path to the directory containing physical.yaml,
                semantic.yaml, and policy.yaml manifest files.
            transport: Optional transport instance. Defaults to StdioTransport.
        """
        self._config_dir = Path(config_dir)
        self._transport = transport or StdioTransport()
        self._dispatcher = Dispatcher()
        self._backend_registry = BackendRegistry()
        self._manifest_index: ManifestIndex | None = None
        self._running = False

    async def start(self) -> None:
        """Start the server.

        Loads manifests, initializes backends, registers handlers,
        starts the transport, and enters the message loop.
        """
        logger.info("Starting ADP Hypervisor server")

        self._load_manifests()
        await self._initialize_backends()
        self._register_handlers()

        await self._transport.start()
        self._running = True
        logger.info("ADP Hypervisor server started, waiting for messages")

        try:
            await self._message_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the server, shutting down backends and transport."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping ADP Hypervisor server")

        await self._backend_registry.shutdown_all()
        await self._transport.stop()

        logger.info("ADP Hypervisor server stopped")

    async def run(self) -> None:
        """Run the server with graceful shutdown on SIGINT/SIGTERM."""
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        server_task = asyncio.create_task(self.start())

        await asyncio.wait(
            [server_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not server_task.done():
            await self.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
        else:
            # Propagate exceptions from start()
            server_task.result()

    def _load_manifests(self) -> None:
        """Load manifests from the config directory and build the index."""
        physical_path = self._config_dir / "physical.yaml"
        semantic_path = self._config_dir / "semantic.yaml"
        policy_path = self._config_dir / "policy.yaml"

        for path in (physical_path, semantic_path, policy_path):
            if not path.exists():
                raise FileNotFoundError(f"Manifest file not found: {path}")

        provider = YamlManifestProvider(
            physical_path=physical_path,
            semantic_path=semantic_path,
            policy_path=policy_path,
        )
        provider.load()

        self._manifest_index = ManifestIndex(provider)
        logger.info("Manifests loaded from %s", self._config_dir)

    async def _initialize_backends(self) -> None:
        """Create and connect backend instances from the physical manifest."""
        assert self._manifest_index is not None

        for backend_def in self._manifest_index.list_backends():
            backend = _create_backend(backend_def)
            if backend is None:
                logger.warning(
                    "No factory for backend type %s (backend: %s), skipping",
                    backend_def.type,
                    backend_def.id,
                )
                continue

            self._backend_registry.register(backend)

        await self._backend_registry.initialize_all()

    def _register_handlers(self) -> None:
        """Create and register all ADP handlers with the dispatcher."""
        assert self._manifest_index is not None

        handlers = [
            InitializeHandler(),
            PingHandler(),
            DiscoverHandler(self._manifest_index),
            DescribeHandler(self._manifest_index),
            ValidateHandler(self._manifest_index),
            ExecuteHandler(self._manifest_index, self._backend_registry),
        ]

        for handler in handlers:
            self._dispatcher.register_handler(handler)

        logger.info(
            "Registered handlers: %s",
            ", ".join(self._dispatcher.get_registered_methods()),
        )

    async def _message_loop(self) -> None:
        """Read messages from transport and dispatch responses."""
        async for message in self._transport.receive():
            if not self._running:
                break
            response = await self._dispatcher.dispatch(message)
            await self._transport.send(response)
