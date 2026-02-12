"""
Backend abstract base class.

Defines the abstract interface that all ADP backend implementations must follow.
Each backend handles connection management and intent execution for a specific
data source type.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from adp_hypervisor.manifest.physical import BackendDefinition
from adp_hypervisor.protocol.types import Intent

logger = logging.getLogger(__name__)


@dataclass
class BackendResult:
    """Result from a backend execution.

    Attributes:
        rows: The result rows as a list of field-value mappings.
        metadata: Optional metadata about the execution (e.g., duration, source system).
    """

    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class Backend(ABC):
    """Abstract base class for all ADP backends.

    A backend is responsible for interacting with a specific data source type
    (e.g., RDBMS, Vector DB). It handles connection lifecycle, intent
    validation, and intent execution.

    Subclasses must implement all abstract methods.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        self._definition = definition

    @property
    def backend_id(self) -> str:
        """Return the unique identifier for this backend."""
        return self._definition.id

    @property
    def definition(self) -> BackendDefinition:
        """Return the backend definition from the physical manifest."""
        return self._definition

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source.

        Raises:
            ConnectionError: If the connection cannot be established.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection and release resources."""

    @abstractmethod
    async def execute(self, source: str, intent: Intent) -> BackendResult:
        """Execute an intent against the data source.

        Args:
            source: The source identifier.
            intent: The intent to execute.

        Returns:
            The execution result containing rows and optional metadata.
        """
