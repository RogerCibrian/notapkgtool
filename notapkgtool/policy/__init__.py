"""Deployment policy and update management for NAPT.

This module provides policy enforcement for application updates including
version comparison strategies, hash-based change detection, and deployment
wave/ring management.

Modules:

updates : module
    Update policies for deciding when to stage new application versions.

Public API:

UpdatePolicy : class
    Configuration for update staging decisions.
should_stage : function
    Determine if a new version should be staged based on policy.

Example:
    from notapkgtool.policy import UpdatePolicy, should_stage

    policy = UpdatePolicy(
        strategy="version_then_hash",
        comparator="semver",
    )

    stage_it = should_stage(
        remote_version="1.2.0",
        remote_hash="abc123...",
        current_version="1.1.9",
        current_hash="def456...",
        policy=policy,
    )
    print(f"Should stage: {stage_it}")  # True

"""

# Future: Import when updates.py is fully implemented
# from .updates import UpdatePolicy, should_stage
# __all__ = ["UpdatePolicy", "should_stage"]

__all__ = []
