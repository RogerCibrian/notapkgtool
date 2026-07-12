# Copyright 2025 Roger Cibrian
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

"""Group validation for promotion plans.

A planned action names its assignment groups, so an unresolvable group —
a typo in ring configuration, a deleted Entra ID group — is knowable
before anything mutates the tenant. Checking up front turns what would
be a mid-run abort (leaving a half-applied plan) into either a failed
plan that never reaches review, or an apply that refuses to start.

Used by the authenticated ``napt promote plan`` modes (a plan with an
unresolvable group fails instead of becoming a reviewable promotion PR)
and by ``napt promote apply`` as a preflight before executing any
action. Offline plans skip validation — the apply preflight is the
backstop for anything they produce.
"""

from __future__ import annotations

from typing import Any

from napt.exceptions import ConfigError
from napt.upload.graph import resolve_assignment_target

__all__ = ["unresolvable_groups"]


def unresolvable_groups(
    access_token: str,
    actions: list[dict[str, Any]],
    group_id_cache: dict[str, str] | None = None,
) -> list[str]:
    """Resolves every group named in the actions, collecting failures.

    Each distinct group is resolved once. Successful resolutions land in
    the shared cache, so a subsequent apply pass re-resolves nothing.

    Args:
        access_token: Bearer token for Graph API.
        actions: Planned action dicts (each may carry a "groups" list).
        group_id_cache: Shared cache for group name resolution. A new
            cache is used when omitted.

    Returns:
        One failure description per unresolvable group, sorted for
            deterministic output. Empty when every group resolves.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On Graph API failures.

    """
    cache = group_id_cache if group_id_cache is not None else {}
    failures: list[str] = []
    seen: set[str] = set()

    for action in actions:
        for group in action.get("groups", []):
            if group in seen:
                continue
            seen.add(group)
            try:
                resolve_assignment_target(access_token, group, cache)
            except ConfigError as err:
                failures.append(str(err))

    failures.sort()
    return failures
