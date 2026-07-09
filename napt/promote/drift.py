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

"""Assignment drift detection for NAPT deployment promotion.

Compares what deployment state says should be assigned in Intune against
what actually is, and reports every discrepancy as a finding. Strictly
observational: drift is warned about and never corrected — manual admin
changes are deliberately left alone.

Finding kinds:

- ``missing_app``: State references a release whose stamped Intune entry
    no longer exists.
- ``missing_assignment``: An assignment NAPT applied (ring group or
    install group) is no longer present.
- ``intent_mismatch``: An expected assignment exists with a different
    intent.
- ``unexpected_assignment``: A NAPT-stamped app carries an assignment
    NAPT did not make (typically admin-made; left alone).
- ``orphaned_release``: A stamped app exists for a release that no state
    file references (e.g., a crashed run replaced by newest-wins).
- ``unknown_app``: A stamped app references a recipe id with no recipe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from napt.state import deployment_state_path, load_deployment_state
from napt.upload.graph import (
    get_app_assignments,
    resolve_assignment_target,
)
from napt.upload.stamp import ENTRY_INSTALL, ENTRY_UPDATE, parse_stamp

__all__ = ["detect_drift"]


def _target_key(target: dict[str, Any] | None) -> tuple[str, str]:
    """Returns a comparable identity for an assignment target."""
    target = target or {}
    return (target.get("@odata.type", ""), target.get("groupId", ""))


def _describe_target(target: dict[str, Any] | None, names: dict) -> str:
    """Returns a human-readable name for an assignment target."""
    target = target or {}
    odata_type = target.get("@odata.type", "")
    if "allLicensedUsers" in odata_type:
        return "All Users"
    if "allDevices" in odata_type:
        return "All Devices"
    group_id = target.get("groupId", "")
    return names.get(_target_key(target), f"group {group_id or 'unknown'}")


def _referenced_shas(state: dict[str, Any]) -> set[str]:
    """Returns every release hash a deployment state file references."""
    shas: set[str] = set()
    for section in ("deployed", "pending"):
        entry = state.get(section) or {}
        if entry.get("sha256"):
            shas.add(entry["sha256"])
    for holder in (state.get("rings") or {}).values():
        if holder.get("sha256"):
            shas.add(holder["sha256"])
    for retained in state.get("retained") or []:
        if retained.get("sha256"):
            shas.add(retained["sha256"])
    install_assigned = state.get("install_assigned") or {}
    if install_assigned.get("sha256"):
        shas.add(install_assigned["sha256"])
    return shas


def _expected_assignments(
    access_token: str,
    config: dict[str, Any],
    state: dict[str, Any],
    group_id_cache: dict[str, str],
    names: dict,
) -> dict[tuple[str, str], dict[tuple[str, str], str]]:
    """Builds the expected assignment map for one app.

    Args:
        access_token: Bearer token for Graph API.
        config: The app's effective configuration.
        state: The app's deployment state.
        group_id_cache: Shared cache for group name resolution.
        names: Target-key to configured-name map, filled as a side
            effect for readable findings.

    Returns:
        A map of (entry type, release sha256) to a map of target key to
            expected intent.

    """
    deployment = config["deployment"]
    rings_by_name = {ring["name"]: ring for ring in deployment["rings"]}
    expected: dict[tuple[str, str], dict[tuple[str, str], str]] = {}

    for ring_name, holder in (state.get("rings") or {}).items():
        ring_cfg = rings_by_name.get(ring_name)
        if ring_cfg is None or not holder.get("sha256"):
            continue  # Ring removed from config; nothing is expected.
        slot = expected.setdefault((ENTRY_UPDATE, holder["sha256"]), {})
        for group in ring_cfg["groups"]:
            target = resolve_assignment_target(access_token, group, group_id_cache)
            key = _target_key(target)
            names[key] = group
            slot[key] = "required"

    install_assigned = state.get("install_assigned") or {}
    install_cfg = deployment["install"]
    if install_assigned.get("sha256") and install_cfg["groups"]:
        slot = expected.setdefault((ENTRY_INSTALL, install_assigned["sha256"]), {})
        for group in install_cfg["groups"]:
            target = resolve_assignment_target(access_token, group, group_id_cache)
            key = _target_key(target)
            names[key] = group
            slot[key] = install_cfg["intent"]

    return expected


def detect_drift(
    access_token: str,
    configs: dict[str, dict[str, Any]],
    deployment_dir: Path,
    existing_apps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detects assignment drift between deployment state and Intune.

    Args:
        access_token: Bearer token for Graph API.
        configs: Effective configurations keyed by recipe id.
        deployment_dir: Directory holding per-app deployment state files.
        existing_apps: Mobile app dicts from list_mobile_apps.

    Returns:
        Finding dicts, each with "app_id", "kind", and "detail" keys,
            sorted for deterministic output. Empty when Intune matches
            state.

    Raises:
        AuthError: On 401 or 403.
        ConfigError: If a configured group cannot be resolved.
        NetworkError: On Graph API failures.
        StateError: On a corrupted deployment state file.

    """
    findings: list[dict[str, Any]] = []
    group_id_cache: dict[str, str] = {}
    names: dict = {}

    stamped_by_recipe: dict[str, list[tuple[dict, dict]]] = {}
    for app in existing_apps:
        stamp = parse_stamp(app.get("notes"))
        if stamp is None:
            continue
        if stamp["id"] not in configs:
            findings.append(
                {
                    "app_id": stamp["id"],
                    "kind": "unknown_app",
                    "detail": (
                        f"stamped app '{app.get('displayName', app['id'])}' "
                        f"references recipe id '{stamp['id']}', which has "
                        "no recipe"
                    ),
                }
            )
            continue
        stamped_by_recipe.setdefault(stamp["id"], []).append((stamp, app))

    for app_id, config in configs.items():
        state = load_deployment_state(deployment_state_path(deployment_dir, app_id))
        expected = _expected_assignments(
            access_token, config, state, group_id_cache, names
        )
        referenced = _referenced_shas(state)
        stamped = stamped_by_recipe.get(app_id, [])
        stamped_keys = {(s["entry"], s["sha256"]) for s, _ in stamped}

        for entry, sha in expected:
            if (entry, sha) not in stamped_keys:
                findings.append(
                    {
                        "app_id": app_id,
                        "kind": "missing_app",
                        "detail": (
                            f"state expects a stamped {entry} entry for "
                            f"release {sha[:12]}, but none exists in the "
                            "tenant"
                        ),
                    }
                )

        for stamp, app in stamped:
            entry = stamp["entry"]
            sha = stamp["sha256"]
            if sha not in referenced:
                findings.append(
                    {
                        "app_id": app_id,
                        "kind": "orphaned_release",
                        "detail": (
                            f"stamped {entry} entry "
                            f"'{app.get('displayName', app['id'])}' for "
                            f"release {sha[:12]} is not referenced by "
                            "deployment state"
                        ),
                    }
                )
                continue

            expected_targets = expected.get((entry, sha), {})
            actual = {
                _target_key(a.get("target")): a
                for a in get_app_assignments(access_token, app["id"])
            }

            for key, intent in expected_targets.items():
                if key not in actual:
                    findings.append(
                        {
                            "app_id": app_id,
                            "kind": "missing_assignment",
                            "detail": (
                                f"{entry} entry for {sha[:12]}: expected "
                                f"assignment '{names.get(key, key)}' "
                                f"({intent}) is not present in Intune"
                            ),
                        }
                    )
                elif actual[key].get("intent") != intent:
                    findings.append(
                        {
                            "app_id": app_id,
                            "kind": "intent_mismatch",
                            "detail": (
                                f"{entry} entry for {sha[:12]}: "
                                f"'{names.get(key, key)}' has intent "
                                f"'{actual[key].get('intent')}' "
                                f"(expected '{intent}')"
                            ),
                        }
                    )

            for key, assignment in actual.items():
                if key not in expected_targets:
                    findings.append(
                        {
                            "app_id": app_id,
                            "kind": "unexpected_assignment",
                            "detail": (
                                f"{entry} entry for {sha[:12]}: assignment "
                                f"'{_describe_target(assignment.get('target'), names)}' "
                                f"({assignment.get('intent')}) was not made "
                                "by NAPT - leaving it alone"
                            ),
                        }
                    )

    findings.sort(key=lambda f: (f["app_id"], f["kind"], f["detail"]))
    return findings


