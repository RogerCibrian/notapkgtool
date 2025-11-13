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
