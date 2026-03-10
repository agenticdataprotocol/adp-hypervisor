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

"""ADP Hypervisor - Agentic Data Protocol Python Implementation."""

__all__ = ["ADPServer"]

__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    """Lazy import to avoid circular dependency with backends."""
    if name == "ADPServer":
        from adp_hypervisor.server import ADPServer

        return ADPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
