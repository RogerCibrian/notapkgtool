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
deployment rings and writes one reviewable plan file per app;
``napt promote apply`` executes each app's plan against Intune
independently.

The core invariant: each ring holds at most one release of an app's Update
entry — the newest release that has reached it. Promotion advances the
published release into the next ring once it has held its current ring for
the ring's ``promote_after_days``.

Assignment drift — differences between what deployment state says should
be assigned and what Intune actually has — is detected on every apply and
on ``plan --check-drift``, and is always reported, never corrected.

Publications whose deployment state writeback was lost (e.g. a failed CI
push after a successful upload) are recovered from tenant evidence on
every apply and on ``plan --reconcile``.

Modules:
    planner - Plan computation and plan file writing.
    applier - Plan execution against Intune.
    preflight - Group resolution validation before assignment.
    drift - Assignment drift detection.
    reconcile - Lost publication writeback recovery.
"""
