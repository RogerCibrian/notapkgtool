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

"""Deployment promotion for NAPT.

Implements ring-based promotion of published apps: ``napt promote plan``
computes which releases should enter or advance through the configured
deployment rings and writes a reviewable plan file; ``napt promote apply``
(upcoming) executes a plan against Intune.

The core invariant: each ring holds at most one release of an app's Update
entry — the newest release that has reached it. Promotion advances the
deployed release into the next ring once it has held its current ring for
the ring's ``promote_after_days``.

Assignment drift — differences between what deployment state says should
be assigned and what Intune actually has — is detected on every apply and
on ``plan --check-drift``, and is always reported, never corrected.
"""

from .applier import apply_plan, load_plan_file
from .drift import check_drift, detect_drift
from .planner import (
    plan_path_for,
    plan_promotions,
    resolve_state_dir,
    write_plan_file,
)

__all__ = [
    "apply_plan",
    "check_drift",
    "detect_drift",
    "load_plan_file",
    "plan_path_for",
    "plan_promotions",
    "resolve_state_dir",
    "write_plan_file",
]
