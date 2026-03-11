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
Policy Enforcer.

Enforces ACCESS policy rules defined in the policy manifest.
Delegates authentication to ``Authenticator`` and role resolution
to ``RoleResolver``, then uses ``ManifestIndex`` for policy lookups.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from adp_hypervisor.policy.authenticator import Authenticator
from adp_hypervisor.policy.role_resolver import RoleResolver
from adp_hypervisor.protocol.errors import UnauthorizedError
from adp_hypervisor.protocol.types import IntentClass

if TYPE_CHECKING:
    from adp_hypervisor.manifest.index import ManifestIndex
    from adp_hypervisor.manifest.policy import AccessPolicy
    from adp_hypervisor.manifest.semantic import CuratedResource

logger = logging.getLogger(__name__)


class PolicyEnforcer:
    """Enforces ACCESS policy rules for ADP requests.

    Uses ``ManifestIndex`` for policy lookups, ``Authenticator`` for
    extracting user identity, and ``RoleResolver`` for mapping users
    to roles.

    ACCESS enforcement follows the closed-by-default model: if no ACCESS
    policy matches a resource, all access is denied regardless of role
    or intent class.
    """

    def __init__(
        self,
        manifest_index: ManifestIndex,
        authenticator: Authenticator,
        role_resolver: RoleResolver,
    ) -> None:
        """Initialize the enforcer.

        Args:
            manifest_index: Index for looking up ACCESS policies.
            authenticator: Authenticator for extracting user identity.
            role_resolver: Resolver for mapping usernames to roles.
        """
        self._manifest_index = manifest_index
        self._authenticator = authenticator
        self._role_resolver = role_resolver

    def resolve_role(self, params: dict[str, Any]) -> str:
        """Resolve the current request's role from params metadata.

        Authenticates the user via ``Authenticator.authenticate()``,
        then resolves the role via ``RoleResolver.resolve()``.

        Args:
            params: The raw JSON-RPC request parameters dict.

        Returns:
            The resolved role string.
        """
        user = self._authenticator.authenticate(params)
        role = self._role_resolver.resolve(user)
        logger.debug("Role resolved: user=%r, role=%r", user, role)
        return role

    def check_access(self, resource_id: str, role: str, intent_class: IntentClass) -> None:
        """Check ACCESS policy for a (resource, role, intent) triple.

        Follows the ACCESS resolution algorithm defined in the policy schema:

        1. Collect all ACCESS policies at the highest specificity matching
           ``resource_id`` (via ``ManifestIndex``).
        2. Merge ``roles`` across matched policies: for the given ``role``,
           take the **union** of ``allowedIntents``.
        3. If any ``allowedIntents`` contains ``"*"`` (wildcard), treat
           as "all intent classes allowed" for that role.
        4. Check if ``intent_class`` is in the merged allowed-intents set.
        5. If no ACCESS policy matches (empty set) → **deny** (closed-by-default).

        Args:
            resource_id: The target resource ID.
            role: The resolved role of the current user.
            intent_class: The intent class being requested.

        Raises:
            UnauthorizedError: If the role is not permitted to use the
                intent class on the resource.
        """
        policies = self._manifest_index.get_access_policies_for_resource(resource_id)

        if not policies:
            logger.warning(
                "Access denied: no policy for resource=%r, role=%r, intent=%s",
                resource_id,
                role,
                intent_class.value,
            )
            raise UnauthorizedError(
                f"Access denied: no ACCESS policy matches resource {resource_id!r}"
            )

        allowed_intents = self._merge_allowed_intents(policies, role)

        if not allowed_intents:
            logger.warning(
                "Access denied: role not permitted, resource=%r, role=%r, intent=%s",
                resource_id,
                role,
                intent_class.value,
            )
            raise UnauthorizedError(
                f"Access denied: role {role!r} is not permitted " f"for resource {resource_id!r}"
            )

        if IntentClass.WILDCARD in allowed_intents:
            logger.debug(
                "Access granted (wildcard): resource=%r, role=%r, intent=%s",
                resource_id,
                role,
                intent_class.value,
            )
            return

        if intent_class not in allowed_intents:
            logger.warning(
                "Access denied: intent not allowed, resource=%r, role=%r, intent=%s",
                resource_id,
                role,
                intent_class.value,
            )
            raise UnauthorizedError(
                f"Access denied: role {role!r} cannot use intent "
                f"{intent_class.value} on resource {resource_id!r}"
            )

        logger.debug(
            "Access granted: resource=%r, role=%r, intent=%s",
            resource_id,
            role,
            intent_class.value,
        )

    def filter_accessible_resources(
        self, resources: list[CuratedResource], role: str
    ) -> list[CuratedResource]:
        """Filter resources to only those the role has any access to.

        A resource is accessible if at least one ACCESS policy matches
        it and the merged role entries include the given role with at
        least one allowed intent.

        Used by ``DiscoverHandler`` to hide resources the caller cannot
        access.

        Args:
            resources: The full list of curated resources.
            role: The resolved role of the current user.

        Returns:
            A filtered list containing only accessible resources.
        """
        cache: dict[str, bool] = {}
        result: list[CuratedResource] = []
        for resource in resources:
            rid = resource.resource_id
            if rid not in cache:
                cache[rid] = self._is_resource_accessible(rid, role)
            if cache[rid]:
                result.append(resource)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _merge_allowed_intents(self, policies: list[AccessPolicy], role: str) -> set[IntentClass]:
        """Merge allowedIntents for a role across multiple ACCESS policies.

        Per the schema spec, when multiple ACCESS policies share the
        highest specificity, their ``roles`` entries are merged by
        taking the union of ``allowedIntents`` for each role.

        Args:
            policies: ACCESS policies at the same specificity level.
            role: The role to look up.

        Returns:
            The union of allowed intent classes for the role.
        """
        allowed: set[IntentClass] = set()
        for policy in policies:
            for entry in policy.roles:
                if entry.role == role:
                    allowed.update(entry.allowed_intents)
        return allowed

    def _is_resource_accessible(self, resource_id: str, role: str) -> bool:
        """Check if a role has any access to a resource.

        Args:
            resource_id: The resource ID to check.
            role: The role to check access for.

        Returns:
            True if the role has at least one allowed intent on the resource.
        """
        policies = self._manifest_index.get_access_policies_for_resource(resource_id)
        if not policies:
            return False
        allowed = self._merge_allowed_intents(policies, role)
        return bool(allowed)
