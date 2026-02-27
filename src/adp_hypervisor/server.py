"""
ADP Hypervisor main server class.

Orchestrates the lifecycle of the ADP server by wiring together transport,
protocol dispatcher, handlers, manifest provider, and backend registry.
"""

import asyncio
import logging
import signal

from adp_hypervisor.handlers import (
    DescribeHandler,
    DiscoverHandler,
    ExecuteHandler,
    InitializeHandler,
    PingHandler,
    ValidateHandler,
)
from adp_hypervisor.manifest.index import (
    ManifestIndex,
    set_global_manifest_index,
)
from adp_hypervisor.manifest.physical import (
    BackendDefinition,
    BackendType,
)
from adp_hypervisor.manifest.provider import ManifestProvider
from adp_hypervisor.protocol.dispatcher import Dispatcher
from adp_hypervisor.transport.base import Transport
from adp_hypervisor.transport.stdio import StdioTransport
from backends.base import Backend
from backends.registry import BackendRegistry

logger = logging.getLogger(__name__)


def _create_backend(definition: BackendDefinition) -> Backend | None:
    """Create a backend instance from a definition, using lazy imports.

    Selection is by both type and provider: e.g. RDBMS with provider
    "postgresql" maps to PostgresBackend; RDBMS with "mysql" is not yet
    implemented and returns None.

    Args:
        definition: The backend definition from the physical manifest.

    Returns:
        A backend instance, or None if the type+provider is not supported.
    """
    provider = definition.provider.strip().lower()

    if definition.type == BackendType.RDBMS:
        if provider == "postgresql":
            from backends.rdbms.postgres import PostgresBackend

            return PostgresBackend(definition=definition)
        return None

    if definition.type == BackendType.VECTOR:
        if provider == "pgvector":
            from backends.vector.pgvector import PgVectorBackend

            return PgVectorBackend(definition=definition)
        return None

    if definition.type == BackendType.NOSQL:
        if provider == "mongodb":
            from backends.nosql.mongodb import MongoDBBackend

            return MongoDBBackend(definition=definition)
        return None

    return None


class ADPServer:
    """Main ADP Hypervisor server.

    Loads manifests, initializes backends, registers handlers, and runs the
    transport message loop.
    """

    def __init__(
        self,
        manifest_provider: ManifestProvider,
        transport: Transport | None = None,
    ) -> None:
        """Initialize the server.

        Args:
            manifest_provider: Provider that loads physical, semantic,
                and policy manifests from any storage backend.
            transport: Optional transport instance. Defaults to StdioTransport.
        """
        self._manifest_provider = manifest_provider
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

        # Clear the global ManifestIndex to avoid leaking it across server
        # lifecycles within the same process (for example, in tests or when
        # multiple servers are created sequentially).
        set_global_manifest_index(None)

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
        """Load manifests from the provider and build the index."""
        self._manifest_provider.load()
        self._manifest_index = ManifestIndex(self._manifest_provider)
        # Expose manifest index globally so backends can resolve resources
        set_global_manifest_index(self._manifest_index)
        logger.info("Manifests loaded")

    async def _initialize_backends(self) -> None:
        """Create and connect backend instances from the physical manifest."""
        assert self._manifest_index is not None

        for backend_def in self._manifest_index.list_backends():
            backend = _create_backend(backend_def)
            if backend is None:
                logger.warning(
                    "No factory for backend type %s provider %s (backend: %s), skipping",
                    backend_def.type,
                    backend_def.provider,
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
