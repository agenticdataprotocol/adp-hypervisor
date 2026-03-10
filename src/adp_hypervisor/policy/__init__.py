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

"""ADP Policy enforcement layer."""

from adp_hypervisor.policy.authenticator import Authenticator
from adp_hypervisor.policy.basic_authenticator import BasicAuthenticator
from adp_hypervisor.policy.enforcer import PolicyEnforcer
from adp_hypervisor.policy.role_resolver import RoleResolver, UserRoleConfig
from adp_hypervisor.policy.yaml_role_resolver import YamlRoleResolver

__all__ = [
    # Authentication
    "Authenticator",
    "BasicAuthenticator",
    # Enforcement
    "PolicyEnforcer",
    # Role resolution
    "RoleResolver",
    "UserRoleConfig",
    "YamlRoleResolver",
]
