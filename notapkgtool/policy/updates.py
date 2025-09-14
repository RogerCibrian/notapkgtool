"""
Update decision policy for NAPT.

Determines whether a newly discovered remote artifact should be staged,
based on version, hash, and org policy.

Usage:
    from notapkgtool.policy.updates import should_stage, UpdatePolicy

    decision = should_stage(
        remote_version="124.0.6367.91",
        remote_hash="abc...",
        current_version="124.0.6367.70",
        current_hash="def...",
        policy=UpdatePolicy(strategy="version_then_hash", allow_same_version_hash_change=True, comparator="semver"),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from notapkgtool.processors.version_check import is_newer


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
    """
    Decide whether to stage a newly discovered artifact.

    Inputs:
      remote_version: version found during discovery (string as parsed for the comparator)
      remote_hash   : SHA-256 (hex) of the newly downloaded artifact
      current_version: version we last staged/deployed (None if none)
      current_hash   : hash we last staged/deployed (None if none)
      policy        : UpdatePolicy controlling the decision algorithm

    Returns:
      True if we should stage the new artifact, False otherwise.
    """
    # If we have no prior state, stage the first artifact.
    if current_version is None and current_hash is None:
        return True

    # Normalized comparisons
    version_changed = (
        True
        if current_version is None
        else is_newer(remote_version, current_version, policy.comparator)
        or remote_version != current_version
        # Treat "different version string" as change even if comparator treats them equal
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
