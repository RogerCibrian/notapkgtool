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

"""Update decision policy for NAPT.

Determines whether a newly discovered remote artifact should be staged,
based on version, hash, and org policy.

Example:
    Check if a new version should be staged:

        from notapkgtool.policy.updates import should_stage, UpdatePolicy

        decision = should_stage(
            remote_version="124.0.6367.91",
            remote_hash="abc...",
            current_version="124.0.6367.70",
            current_hash="def...",
            policy=UpdatePolicy(
                strategy="version_then_hash",
                allow_same_version_hash_change=True,
                comparator="semver"
            ),
        )

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from notapkgtool.versioning import is_newer_any

Strategy = Literal["version_only", "version_then_hash", "hash_or_version", "hash_only"]
Comparator = Literal["semver", "lexicographic"]


@dataclass(frozen=True)
class UpdatePolicy:
    strategy: Strategy = "version_then_hash"
    allow_same_version_hash_change: bool = True
    comparator: Comparator = "semver"


def should_stage(
    *,
    remote_version: str,
    remote_hash: str,
    current_version: str | None,
    current_hash: str | None,
    policy: UpdatePolicy,
) -> bool:
    """Decide whether to stage a newly discovered artifact.

    Compares remote version/hash against current state using the configured
    policy strategy to determine if the new artifact should be staged.

    Args:
        remote_version: Version found during discovery.
        remote_hash: SHA-256 hash of the newly downloaded artifact.
        current_version: Version we last staged/deployed (None if none).
        current_hash: Hash we last staged/deployed (None if none).
        policy: UpdatePolicy controlling the decision algorithm.

    Returns:
        True if the new artifact should be staged, False otherwise.

    """
    # If we have no prior state, stage the first artifact.
    if current_version is None and current_hash is None:
        return True

    # Normalized comparisons
    version_changed = (
        True
        if current_version is None
        else is_newer_any(remote_version, current_version, policy.comparator)
        or remote_version != current_version
        # Treat "different version string" as change even if comparator
        # treats them equal
    )

    hash_changed = (current_hash or "").lower() != (remote_hash or "").lower()

    if policy.strategy == "version_only":
        return version_changed

    if policy.strategy == "version_then_hash":
        if version_changed:
            return True
        if not version_changed and policy.allow_same_version_hash_change:
            # Same version string but bits changed (repack, resign, silent fix)
            return hash_changed
        return False

    if policy.strategy == "hash_or_version":
        return version_changed or hash_changed

    if policy.strategy == "hash_only":
        return hash_changed

    # Safe default: do not stage on unknown strategy
    return False
