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
Role Resolver.

Defines the role resolution interface (ABC) and the user-role config model.
"""

import abc

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import ADPModel


class UserRoleConfig(ADPModel):
    """Configuration for user-to-role mapping.

    Loaded from ``users.yaml`` at server startup. Maps usernames to roles
    and provides a default role for unknown users who provide valid credentials.
    """

    default_role: str = PydanticField(
        default="default",
        description="Role assigned to unknown users who provide valid credentials",
    )
    users: dict[str, str] = PydanticField(
        default_factory=dict,
        description="Mapping of username to role (e.g. {'admin': 'admin', 'alice': 'analyst'})",
    )


class RoleResolver(abc.ABC):
    """Abstract interface for mapping a username to a role.

    Implementations look up the role for a given username using
    a configured data source (e.g. YAML file, Gravitino, LDAP).
    """

    @abc.abstractmethod
    def resolve(self, user: str) -> str:
        """Resolve a username to a role string.

        Args:
            user: The authenticated username.

        Returns:
            The resolved role string.
        """
