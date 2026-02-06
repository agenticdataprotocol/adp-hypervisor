"""
Backend Registry.

Manages the lifecycle and lookup of backend instances. The registry is used
during server initialization to connect all configured backends and provides
access to them by backend ID during request handling.
"""

import logging
import threading

from backends.base import Backend

logger = logging.getLogger(__name__)


class BackendRegistry:
    """Registry for managing backend instances.

    Provides registration, lookup, and lifecycle management for backends.
    All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backends: dict[str, Backend] = {}

    def register(self, backend: Backend) -> None:
        """Register a backend instance.

        Args:
            backend: The backend instance to register.

        Raises:
            ValueError: If a backend with the same ID is already registered.
        """
        backend_id = backend.backend_id
        with self._lock:
            if backend_id in self._backends:
                raise ValueError(f"Backend already registered: {backend_id!r}")
            self._backends[backend_id] = backend
        logger.debug("Registered backend: %s", backend_id)

    def get(self, backend_id: str) -> Backend | None:
        """Get a backend by ID.

        Args:
            backend_id: The unique backend identifier.

        Returns:
            The backend instance, or None if not found.
        """
        with self._lock:
            return self._backends.get(backend_id)

    def list_backends(self) -> list[Backend]:
        """Return all registered backend instances."""
        with self._lock:
            return list(self._backends.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._backends)

    def __contains__(self, backend_id: str) -> bool:
        with self._lock:
            return backend_id in self._backends

    async def initialize_all(self) -> None:
        """Connect all registered backends.

        Raises:
            ConnectionError: If any backend fails to connect.
        """
        with self._lock:
            backends = list(self._backends.values())
        for backend in backends:
            logger.info("Connecting backend: %s", backend.backend_id)
            await backend.connect()
        logger.info("All %d backend(s) connected", len(backends))

    async def shutdown_all(self) -> None:
        """Disconnect all registered backends.

        Logs warnings for backends that fail to disconnect but does not raise.
        """
        with self._lock:
            backends = list(self._backends.values())
        for backend in backends:
            try:
                logger.info("Disconnecting backend: %s", backend.backend_id)
                await backend.disconnect()
            except Exception:
                logger.warning(
                    "Failed to disconnect backend: %s", backend.backend_id, exc_info=True
                )
        logger.info("All backends disconnected")
