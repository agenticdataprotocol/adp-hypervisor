"""
NoSQL Backend base class.

Defines the abstract interface that all NoSQL backend implementations must follow.
Subclasses handle connection management, schema discovery, and intent execution
for their specific NoSQL database.
"""

from abc import abstractmethod

from adp_hypervisor.manifest.physical import BackendDefinition
from adp_hypervisor.protocol.types import Field
from backends.base import Backend


class NOSQLBackend(Backend):
    """Base class for NoSQL backends.

    Extends the generic Backend interface with schema discovery.
    Subclasses must implement connection management, schema discovery,
    and intent execution for their specific NoSQL database.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)

    @abstractmethod
    async def get_schema(self, source: str) -> list[Field]:
        """Discover the schema for a collection.

        Args:
            source: The source identifier (collection name).

        Returns:
            A list of field definitions describing the source schema.
        """
