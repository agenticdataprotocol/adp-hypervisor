"""
Execute Handler.

Implements the adp.execute method which executes a validated Intent IR
against the appropriate backend and returns results with execution metadata.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from adp_hypervisor.handlers.base import Handler
from adp_hypervisor.handlers.validate import ValidateHandler
from adp_hypervisor.manifest.policy import OperationalRule
from adp_hypervisor.protocol.errors import (
    ExecutionFailedError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from adp_hypervisor.protocol.types import (
    ExecuteRequestParams,
    ExecuteResult,
    ExecutionMetadata,
    QueryIntent,
    ValidateResult,
)

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex
    from adp_hypervisor.manifest.semantic import CuratedResource
    from adp_hypervisor.protocol.types import (
        IngestIntent,
        LookupIntent,
        ReviseIntent,
    )
    from backends.base import Backend
    from backends.registry import BackendRegistry

logger = logging.getLogger(__name__)


class ExecuteHandler(Handler):
    """Handler for the adp.execute method.

    Validates the intent, enforces policy rules, executes it against
    the appropriate backend, and returns the results with execution metadata.
    """

    def __init__(
        self,
        manifest_index: ManifestIndex,
        backend_registry: BackendRegistry,
    ) -> None:
        """Initialize the handler.

        Args:
            manifest_index: The manifest index to look up resources and policies.
            backend_registry: The registry to look up backend instances.
        """
        self._manifest_index = manifest_index
        self._backend_registry = backend_registry
        self._validate_handler = ValidateHandler(manifest_index)

    @property
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""
        return "adp.execute"

    async def handle(self, params: dict[str, Any]) -> BaseModel:
        """Process an execute request.

        Args:
            params: The JSON-RPC request parameters.

        Returns:
            An ExecuteResult with the query results and execution metadata.

        Raises:
            ResourceNotFoundError: If the resource does not exist.
            ValidationFailedError: If intent validation fails with BLOCKING issues.
            ExecutionFailedError: If the backend is not found or execution fails.
        """
        request = ExecuteRequestParams.model_validate(params)

        resource = self._manifest_index.get_resource(request.resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource not found: {request.resource_id!r}")

        await self._validate_intent(params)
        self._enforce_operational_rules(request.resource_id, request.intent)

        backend = self._resolve_backend(resource)
        source = self._get_source(resource)

        start_ms = time.monotonic()
        try:
            result = await backend.execute(source, request.intent)
        except Exception as exc:
            logger.error(
                "Execution failed: resource=%s, backend=%s",
                request.resource_id,
                resource.backend_id,
                exc_info=True,
            )
            raise ExecutionFailedError(
                f"Execution failed for resource {request.resource_id!r}: {exc}"
            ) from exc
        duration_ms = int((time.monotonic() - start_ms) * 1000)

        # TODO: Implement cursor-based pagination. Currently next_cursor is always None.
        # When implemented, encode pagination state into an opaque cursor token
        # based on the result set and pass it back via next_cursor.

        logger.info(
            "Execute: resource=%s, intent_class=%s, rows=%d, duration_ms=%d",
            request.resource_id,
            request.intent.intent_class,
            len(result.rows),
            duration_ms,
        )

        return ExecuteResult(
            results=result.rows,
            execution_metadata=ExecutionMetadata(
                duration_ms=duration_ms,
                source_system=resource.backend_id,
            ),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def _validate_intent(self, params: dict[str, Any]) -> None:
        """Validate the intent by delegating to ValidateHandler.

        Args:
            params: The raw request parameters (resourceId + intent).

        Raises:
            ValidationFailedError: If validation produces BLOCKING issues.
        """
        result = await self._validate_handler.handle(params)
        assert isinstance(result, ValidateResult)

        if not result.valid:
            issues_data = [
                issue.model_dump(by_alias=True, exclude_none=True)
                for issue in (result.issues or [])
            ]
            raise ValidationFailedError(
                message="Intent validation failed",
                data={"issues": issues_data},
            )

    # ------------------------------------------------------------------
    # Policy enforcement
    # ------------------------------------------------------------------

    def _enforce_operational_rules(
        self,
        resource_id: str,
        intent: LookupIntent | QueryIntent | IngestIntent | ReviseIntent,
    ) -> None:
        """Enforce operational policy rules by modifying the intent in-place.

        Currently enforces:
        - ``enforce_limit``: Caps QueryIntent.limit to the policy maximum.
        """
        policy = self._manifest_index.get_policy(resource_id)
        if policy is None or policy.rules is None:
            return

        for rule in policy.rules:
            if isinstance(rule, OperationalRule) and rule.enforce_limit is not None:
                if isinstance(intent, QueryIntent):
                    if intent.limit is None or intent.limit > rule.enforce_limit:
                        logger.debug(
                            "Capping query limit from %s to %d for resource %s",
                            intent.limit,
                            rule.enforce_limit,
                            resource_id,
                        )
                        intent.limit = rule.enforce_limit

    # ------------------------------------------------------------------
    # Resource / backend resolution
    # ------------------------------------------------------------------

    def _resolve_backend(self, resource: CuratedResource) -> Backend:
        """Look up the backend for a resource.

        Args:
            resource: The curated resource definition.

        Returns:
            The backend instance.

        Raises:
            ExecutionFailedError: If the backend is not registered.
        """
        backend = self._backend_registry.get(resource.backend_id)
        if backend is None:
            raise ExecutionFailedError(
                f"Backend not found: {resource.backend_id!r}. "
                f"Ensure the backend is registered before handling requests."
            )
        return backend

    def _get_source(self, resource: CuratedResource) -> str:
        """Extract the source identifier from a resource.

        Args:
            resource: The curated resource definition.

        Returns:
            The source identifier (e.g., table name).

        Raises:
            ExecutionFailedError: If the resource has no source definitions.
        """
        if not resource.sources:
            raise ExecutionFailedError(
                f"Resource {resource.resource_id!r} has no source definitions"
            )
        return resource.sources[0].source
