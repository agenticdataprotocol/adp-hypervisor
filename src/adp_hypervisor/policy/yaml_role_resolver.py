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
YAML Role Resolver.

Resolves user roles from a YAML-based ``UserRoleConfig``.
"""

import logging

from adp_hypervisor.policy.role_resolver import RoleResolver, UserRoleConfig

logger = logging.getLogger(__name__)


class YamlRoleResolver(RoleResolver):
    """Resolves user roles from a YAML-based ``UserRoleConfig``.

    Known users are mapped to their configured role. Unknown users
    fall back to ``UserRoleConfig.default_role``.
    """

    def __init__(self, config: UserRoleConfig) -> None:
        """Initialize the resolver.

        Args:
            config: User-to-role mapping configuration.
        """
        self._config = config

    @property
    def default_role(self) -> str:
        """Return the default role for unknown users."""
        return self._config.default_role

    def resolve(self, user: str) -> str:
        """Resolve a username to a role string.

        Args:
            user: The authenticated username.

        Returns:
            The role string for the user, or ``default_role``
            if the user is unknown.
        """
        role = self._config.users.get(user)
        if role is None:
            logger.info("Unknown user %r, using default role %r", user, self._config.default_role)
            return self._config.default_role

        logger.debug("Resolved user %r to role %r", user, role)
        return role
