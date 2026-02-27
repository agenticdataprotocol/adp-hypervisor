"""
NoSQL Backend base class.

Defines the abstract interface that all NoSQL backend implementations must follow.
Subclasses handle connection management, schema discovery, and intent execution
for their specific NoSQL database.
"""

from adp_hypervisor.manifest.physical import BackendDefinition
from backends.base import Backend


class NOSQLBackend(Backend):
    """Base class for NoSQL backends.

    Subclasses must implement connection management and intent execution
    for their specific NoSQL database.
    """

    def __init__(self, definition: BackendDefinition) -> None:
        super().__init__(definition)
