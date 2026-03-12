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
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.protocol.errors import (
    ExecutionFailedError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from adp_hypervisor.protocol.types import (
    ExecuteRequestParams,
    ExecuteResult,
    ExecutionMetadata,
    ValidateResult,
)

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex
    from adp_hypervisor.manifest.semantic import CuratedResource
    from backends.base import Backend
    from backends.registry import BackendRegistry

logger = logging.getLogger(__name__)


class ExecuteHandler(Handler):
    """Handler for the adp.execute method.

    Validates the intent, executes it against the appropriate backend,
    and returns the results with execution metadata.
    """

    def __init__(
        self,
        manifest_index: ManifestIndex,
        backend_registry: BackendRegistry,
        policy_enforcer: PolicyEnforcer,
    ) -> None:
        """Initialize the handler.

        Args:
            manifest_index: The manifest index to look up resources.
            backend_registry: The registry to look up backend instances.
            policy_enforcer: The policy enforcer to check access.
        """
        self._manifest_index = manifest_index
        self._backend_registry = backend_registry
        self._policy_enforcer = policy_enforcer
        self._validate_handler = ValidateHandler(manifest_index, policy_enforcer)

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

        resource_id = request.intent.resource_id
        logger.debug(
            "Execute: started resource=%s, intent_class=%s",
            resource_id,
            request.intent.intent_class,
        )

        resource = self._manifest_index.get_resource(resource_id)
        if resource is None:
            raise ResourceNotFoundError(f"Resource not found: {resource_id!r}")

        # Ensure the resource has a concrete source before executing.
        # This keeps error semantics local to the handler and avoids
        # backend-specific failures when the concrete source field is missing.
        source = resource.source_definition.source
        if not source:
            raise ExecutionFailedError(
                f"Resource {resource.resource_id!r} is missing source_definition.source"
            )

        await self._validate_intent(params)
        # TODO: Enforce operational policy rules (e.g., enforce_limit) before execution.

        backend = self._resolve_backend(resource)

        start_s = time.monotonic()
        try:
            result = await backend.execute(request.intent)
        except Exception as exc:
            logger.error(
                "Execution failed: resource=%s, backend=%s",
                request.intent.resource_id,
                resource.backend_id,
                exc_info=True,
            )
            raise ExecutionFailedError(f"Execution failed for resource {resource_id!r}") from exc
        duration_ms = int((time.monotonic() - start_s) * 1000)

        # TODO: Implement cursor-based pagination. Currently next_cursor is always None.
        # When implemented, encode pagination state into an opaque cursor token
        # based on the result set and pass it back via next_cursor.

        logger.info(
            "Execute: resource=%s, backend=%s, intent_class=%s, rows=%d, duration_ms=%d",
            resource_id,
            resource.backend_id,
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
        if not isinstance(result, ValidateResult):
            raise ExecutionFailedError(
                "Internal error: ValidateHandler returned unexpected "
                f"type {type(result)!r}, expected ValidateResult"
            )

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
