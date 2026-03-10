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
Policy Manifest models.

Defines the types for the ADP Curation Plane's policy layer,
which specifies governance rules and constraints for resource access.
Based on the PolicyManifest section of curation.ts.
"""

from typing import Annotated, Literal

from pydantic import Field as PydanticField

from adp_hypervisor.protocol.types import (
    ADPModel,
    IntentClass,
    PredicateOperator,
    ResourceId,
    SortOrder,
)

ResourceSelector = str
"""A resource selector pattern used in ACCESS policies.

Supports the following forms (wildcard ``*`` may appear at most once and only
as the final token):

- Exact: ``"namespace:name"`` — matches a single resource ID.
- All names in one namespace: ``"namespace:*"``
- Namespace prefix: ``"namespace.*"`` or ``"namespace.sub.*"``
- Global catch-all: ``"*"`` — matches every resource.
"""

PolicyCondition = str
"""Condition expression for conditional policy rules (e.g. ``agent_tier == 'BASIC'``)."""


# =============================================================================
# MANDATORY_FILTER Policy
# =============================================================================


class MandatoryFilterPolicy(ADPModel):
    """Mandatory filter policy that enforces required predicates.

    Applies to exactly one resource; ``resource_id`` is required and must be an
    exact resource ID (no wildcards). ``field_id`` is interpreted against that
    resource's schema.
    """

    type: Literal["MANDATORY_FILTER"] = PydanticField(..., description="Type of policy rule")
    resource_id: ResourceId = PydanticField(
        ...,
        description=(
            "Resource ID (exact) this policy applies to. "
            "field_id is interpreted against this resource's schema. No wildcards."
        ),
    )
    field_id: str = PydanticField(..., description="Field identifier for the mandatory filter")
    op: PredicateOperator = PydanticField(..., description="Operator for the mandatory filter")
    value: str | int | float | bool | list[str | int | float | bool] = PydanticField(
        ..., description="Value for the mandatory filter"
    )
    condition: PolicyCondition | None = PydanticField(
        default=None, description="Optional condition for when this policy applies"
    )


# =============================================================================
# OPERATIONAL Policy
# =============================================================================


class OperationalPolicy(ADPModel):
    """Operational policy that applies constraints for resource access.

    Applies to exactly one resource; ``resource_id`` is required and must be an
    exact resource ID (no wildcards). ``default_order_by`` is interpreted against
    that resource's schema.
    """

    type: Literal["OPERATIONAL"] = PydanticField(..., description="Type of policy rule")
    resource_id: ResourceId = PydanticField(
        ...,
        description=(
            "Resource ID (exact) this policy applies to. "
            "default_order_by is interpreted against this resource's schema. No wildcards."
        ),
    )
    enforce_limit: int | None = PydanticField(
        default=None, description="Maximum number of results to return (enforced limit)"
    )
    default_order_by: SortOrder | None = PydanticField(
        default=None, description="Default sort order to apply to the resource"
    )
    condition: PolicyCondition | None = PydanticField(
        default=None, description="Optional condition for when this policy applies"
    )


# =============================================================================
# ACCESS Policy (RBAC)
# =============================================================================


class RoleAccessEntry(ADPModel):
    """Role-to-intents mapping for RBAC access control.

    Defines which intent classes a role is allowed to use on the resource.
    """

    role: str = PydanticField(
        ...,
        description=(
            "Role identifier (e.g. 'admin', 'user'). "
            "The runtime supplies the current role from auth/session when evaluating access."
        ),
    )
    allowed_intents: list[IntentClass] = PydanticField(
        ...,
        description=(
            "Intent classes this role is allowed to use on the resource. "
            "Use '*' to allow all intent classes for this role."
        ),
    )


class AccessPolicy(ADPModel):
    """RBAC-style access policy: restricts which roles can use which intent classes.

    Each ACCESS policy declares which resources it applies to via required
    ``resource_selector``, which uses the ``ResourceSelector`` grammar (exact ID or
    wildcard with ``*`` only as the final token, e.g. ``"com.acme.finance:*"``
    or ``"com.acme.*"``).

    **Closed-by-default**: if no ACCESS policy's ``resource_selector`` matches a
    given resource, runtimes MUST treat the effective roles for that resource as
    empty — no access is granted.
    """

    type: Literal["ACCESS"] = PydanticField(..., description="Type of policy rule")
    resource_selector: ResourceSelector = PydanticField(
        ...,
        description=(
            "Resource selector for which resources this policy applies "
            "(exact resource ID or wildcard, e.g. com.acme.finance:* or com.acme.*)."
        ),
    )
    roles: list[RoleAccessEntry] = PydanticField(
        ...,
        description=(
            "List of role-to-allowed-intents mappings. "
            "Request is allowed only if the current role is listed and the intent class "
            "is in that role's allowed_intents."
        ),
    )


# =============================================================================
# Union / Manifest root
# =============================================================================

Policy = Annotated[
    MandatoryFilterPolicy | OperationalPolicy | AccessPolicy,
    PydanticField(discriminator="type"),
]
"""Union type for all policy types (each appears as a rule in the manifest).

Supported policy types:

- ``MANDATORY_FILTER``: Enforces required predicates that must be included in queries.
- ``OPERATIONAL``: Applies operational constraints (limits, default sorting).
- ``ACCESS``: Role-based allowed intents per resource (RBAC).
"""


class PolicyManifest(ADPModel):
    """Root structure for the policy manifest (policy.yaml).

    **Bootstrap Mode**: For the simplest setup, omit the ``policies`` array entirely.
    No MANDATORY_FILTER or OPERATIONAL enforcements will be applied. ACCESS remains
    closed-by-default: if no ACCESS rule matches a resource, no roles or intent
    classes are permitted for that resource.

    For development, define an explicit catch-all ACCESS rule (e.g.
    ``resourceSelector: "*"``) to open all resources to a default role. See
    ``examples/conf/policy-bootstrap.yaml`` for a reference layout.
    """

    version: str = PydanticField(..., description="Version of the manifest schema")
    policies: list[Policy] | None = PydanticField(
        default=None,
        description=(
            "List of policies. If omitted or empty, no MANDATORY_FILTER or OPERATIONAL "
            "enforcements are applied. ACCESS is always closed-by-default."
        ),
    )
