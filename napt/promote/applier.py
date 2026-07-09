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

"""Promotion apply for NAPT deployment rings.

Executes a promotion plan against Intune: assigns install entries,
enters and advances releases through rings, displaces superseded
releases, and retires them per the retention policy.

Every action is validated against current deployment state before
executing (validate-then-act): stale actions — the deployed release
changed since the plan was written, or the action already applied —
are skipped with a warning instead of failing, so re-running apply
after a partial failure is safe. Deployment state is saved after each
applied action, and ring ``entered_at`` timestamps are written here
and only here.

Displaced releases are found through their provenance stamps (the
tenant is listed once per run), not through deployment state — state
only records the current release's app IDs. A displaced release that
no longer holds any ring moves to the retained list; releases beyond
``deployment.retain_versions`` have their Intune apps deleted.

Assignments NAPT does not manage are preserved: assignment sets are
read, modified, and written back, so admin-made assignments and
non-group targets survive every apply.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from napt.exceptions import StateError
from napt.logging import get_global_logger
from napt.promote.drift import detect_drift
from napt.promote.planner import (
    PLAN_SCHEMA_VERSION,
    load_recipe_configs,
    plan_path_for,
    plan_promotions,
)
from napt.promote.reconcile import reconcile_publications
from napt.state import (
    deployment_state_path,
    load_deployment_state,
    save_deployment_state,
)
from napt.upload.auth import get_access_token
from napt.upload.graph import (
    assign_app,
    build_assignment,
    delete_mobile_app,
    get_app_assignments,
    list_mobile_apps,
    resolve_assignment_target,
)
from napt.upload.stamp import ENTRY_INSTALL, ENTRY_UPDATE, find_stamped_app

__all__ = ["apply_plan", "load_plan_file"]

# Ring assignments target the Update entry, which is gated to devices
# with an older release installed — always a required install.
_RING_INTENT = "required"


def load_plan_file(plan_path: Path) -> list[dict[str, Any]]:
    """Loads planned actions from a plan file.

    Args:
        plan_path: Path to the plan file.

    Returns:
        The planned action dicts.

    Raises:
        StateError: If the plan file contains invalid JSON, lacks an
            actions list, or its schemaVersion is missing or
            unsupported.

    """
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        actions = data["actions"]
    except (json.JSONDecodeError, KeyError, TypeError) as err:
        raise StateError(
            f"Corrupted plan file: {plan_path}. "
            "Re-run 'napt promote plan' to regenerate it."
        ) from err

    found = data.get("schemaVersion")
    if found != PLAN_SCHEMA_VERSION:
        raise StateError(
            f"Unsupported plan schema version {found!r} in {plan_path} "
            f"(this NAPT release supports version {PLAN_SCHEMA_VERSION}). "
            "Re-run 'napt promote plan' to regenerate it."
        )
    return actions


def _strip_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    """Returns an assignment payload safe to send back to the assign action.

    Args:
        assignment: A mobileAppAssignment dict from get_app_assignments.

    Returns:
        The assignment without its read-only id, with the assignment
            @odata.type present.

    """
    cleaned = {key: value for key, value in assignment.items() if key != "id"}
    cleaned.setdefault("@odata.type", "#microsoft.graph.mobileAppAssignment")
    return cleaned


def _target_key(target: dict[str, Any] | None) -> tuple[str, str]:
    """Returns a comparable identity for an assignment target."""
    target = target or {}
    return (target.get("@odata.type", ""), target.get("groupId", ""))


def _add_assignments(
    access_token: str,
    app_id: str,
    targets: list[dict[str, Any]],
    intent: str,
) -> None:
    """Adds assignments for the given targets, preserving everything else.

    Existing assignments with the same targets are replaced (the intent
    may have changed); all other assignments — admin-made groups, other
    virtual targets, exclusions — pass through untouched.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app.
        targets: Resolved assignment target dicts.
        intent: Assignment intent for the added targets.

    """
    keys = {_target_key(t) for t in targets}
    current = get_app_assignments(access_token, app_id)
    kept = [
        _strip_assignment(a)
        for a in current
        if _target_key(a.get("target")) not in keys
    ]
    added = [build_assignment(t, intent) for t in targets]
    assign_app(access_token, app_id, kept + added)


def _remove_assignments(
    access_token: str,
    app_id: str,
    targets: list[dict[str, Any]],
) -> None:
    """Removes assignments for the given targets, preserving the rest.

    Args:
        access_token: Bearer token for Graph API.
        app_id: Graph API object ID of the app.
        targets: Resolved assignment target dicts to unassign.

    """
    keys = {_target_key(t) for t in targets}
    current = get_app_assignments(access_token, app_id)
    kept = [
        _strip_assignment(a)
        for a in current
        if _target_key(a.get("target")) not in keys
    ]
    if len(kept) != len(current):
        assign_app(access_token, app_id, kept)


class _ApplyRun:
    """Holds the shared context of one apply run.

    Caches per-app deployment state (saved after every applied action),
    resolved group IDs, recipe configurations, and the tenant app list.
    """

    def __init__(
        self,
        access_token: str,
        configs: dict[str, dict[str, Any]],
        deployment_dir: Path,
        now: datetime,
    ):
        self.access_token = access_token
        self.configs = configs
        self.deployment_dir = deployment_dir
        self.now = now
        self.existing_apps = list_mobile_apps(access_token)
        self._states: dict[str, dict[str, Any]] = {}
        self._group_ids: dict[str, str] = {}
        self.applied: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []

    def state_for(self, app_id: str) -> dict[str, Any]:
        """Returns the cached deployment state for an app, loading once."""
        if app_id not in self._states:
            self._states[app_id] = load_deployment_state(
                deployment_state_path(self.deployment_dir, app_id)
            )
        return self._states[app_id]

    def save_state(self, app_id: str) -> None:
        """Persists an app's deployment state after an applied action."""
        save_deployment_state(
            self._states[app_id],
            deployment_state_path(self.deployment_dir, app_id),
        )

    def resolve_targets(self, groups: list[str]) -> list[dict[str, Any]]:
        """Resolves group names/IDs to assignment targets with a per-run cache.

        The reserved names "All Users" and "All Devices" map to Intune's
        built-in virtual targets; anything else resolves to an Entra ID
        group target.
        """
        return [
            resolve_assignment_target(self.access_token, group, self._group_ids)
            for group in groups
        ]

    def skip(self, action: dict[str, Any], reason: str) -> None:
        """Records a skipped action and warns."""
        logger = get_global_logger()
        logger.warning(
            "PROMOTE",
            f"Skipping {action['type']} for '{action['app_id']}': {reason}",
        )
        self.skipped.append({"action": action, "reason": reason})


def _holds_any_ring(state: dict[str, Any], sha256: str) -> bool:
    """Returns True when a release still holds at least one ring."""
    return any(
        entry.get("sha256") == sha256 for entry in (state.get("rings") or {}).values()
    )


def _retire_release(run: _ApplyRun, app_id: str, version: str, sha256: str) -> None:
    """Retires a fully displaced release per the retention policy.

    The release joins the retained list (newest last). Releases beyond
    ``deployment.retain_versions`` have their stamped Intune apps
    deleted, oldest first. The currently deployed release is never
    deleted.

    Args:
        run: The apply run context.
        app_id: Recipe identifier.
        version: Displaced release's version string.
        sha256: Displaced release's installer hash.

    """
    logger = get_global_logger()
    state = run.state_for(app_id)
    retained: list[dict[str, Any]] = state.setdefault("retained", [])

    if not any(entry.get("sha256") == sha256 for entry in retained):
        retained.append({"version": version, "sha256": sha256})
        logger.info(
            "PROMOTE",
            f"{app_id}: retained displaced release {version} for rollback",
        )

    retain_limit: int = run.configs[app_id]["deployment"]["retain_versions"]
    deployed = state.get("deployed") or {}
    while len(retained) > retain_limit:
        oldest = retained.pop(0)
        if oldest.get("sha256") == deployed.get("sha256"):
            continue  # Never delete the currently deployed release.
        for entry_type in (ENTRY_INSTALL, ENTRY_UPDATE):
            app = find_stamped_app(
                run.existing_apps, app_id, entry_type, oldest["sha256"]
            )
            if app is not None:
                delete_mobile_app(run.access_token, app["id"])
                logger.info(
                    "PROMOTE",
                    f"{app_id}: deleted retired {entry_type} entry "
                    f"{oldest.get('version')} ({app['id']})",
                )


def _apply_ring_action(run: _ApplyRun, action: dict[str, Any]) -> bool:
    """Applies an enter_ring or advance_ring action.

    Args:
        run: The apply run context.
        action: The planned action.

    Returns:
        True when applied, False when skipped.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]
    ring: str = action["ring"]
    state = run.state_for(app_id)
    deployed = state.get("deployed") or {}

    if deployed.get("sha256") != sha256:
        run.skip(action, "stale action - the deployed release has changed")
        return False
    ring_names = [r["name"] for r in run.configs[app_id]["deployment"]["rings"]]
    if ring not in ring_names:
        run.skip(action, f"ring '{ring}' is no longer configured")
        return False
    rings_state: dict[str, Any] = state.setdefault("rings", {})
    if rings_state.get(ring, {}).get("sha256") == sha256:
        run.skip(action, "already applied")
        return False

    update_app = find_stamped_app(run.existing_apps, app_id, ENTRY_UPDATE, sha256)
    if update_app is None:
        run.skip(action, "no stamped update entry found in the tenant")
        return False

    targets = run.resolve_targets(action["groups"])
    _add_assignments(run.access_token, update_app["id"], targets, _RING_INTENT)

    # Displace the previous holder of this ring (an older release's app).
    previous = rings_state.get(ring)
    if previous and previous.get("sha256") != sha256:
        previous_app = find_stamped_app(
            run.existing_apps, app_id, ENTRY_UPDATE, previous["sha256"]
        )
        if previous_app is not None:
            _remove_assignments(run.access_token, previous_app["id"], targets)
        else:
            get_global_logger().warning(
                "PROMOTE",
                f"{app_id}: displaced release {previous.get('version')} has "
                "no stamped update entry in the tenant; nothing to unassign",
            )

    rings_state[ring] = {
        "version": action["version"],
        "sha256": sha256,
        "entered_at": run.now.isoformat(),
    }

    if previous and previous.get("sha256") != sha256:
        if not _holds_any_ring(state, previous["sha256"]):
            _retire_release(
                run, app_id, previous.get("version", "?"), previous["sha256"]
            )

    run.save_state(app_id)
    run.applied.append(action)
    return True


def _apply_install_action(run: _ApplyRun, action: dict[str, Any]) -> bool:
    """Applies an assign_install action.

    Args:
        run: The apply run context.
        action: The planned action.

    Returns:
        True when applied, False when skipped.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]
    state = run.state_for(app_id)
    deployed = state.get("deployed") or {}

    if deployed.get("sha256") != sha256:
        run.skip(action, "stale action - the deployed release has changed")
        return False
    previous = state.get("install_assigned") or {}
    if previous.get("sha256") == sha256:
        run.skip(action, "already applied")
        return False

    install_app = find_stamped_app(run.existing_apps, app_id, ENTRY_INSTALL, sha256)
    if install_app is None:
        run.skip(action, "no stamped install entry found in the tenant")
        return False

    targets = run.resolve_targets(action["groups"])
    _add_assignments(run.access_token, install_app["id"], targets, action["intent"])

    # Displace the previous release's install assignment.
    previous_sha = previous.get("sha256")
    if previous_sha and previous_sha != sha256:
        previous_app = find_stamped_app(
            run.existing_apps, app_id, ENTRY_INSTALL, previous_sha
        )
        if previous_app is not None:
            _remove_assignments(run.access_token, previous_app["id"], targets)
        if not _holds_any_ring(state, previous_sha):
            _retire_release(
                run, app_id, previous.get("version", "unknown"), previous_sha
            )

    state["install_assigned"] = {
        "version": action["version"],
        "sha256": sha256,
    }
    run.save_state(app_id)
    run.applied.append(action)
    return True


def apply_plan(
    recipes: Path,
    state_dir: Path,
    plan_file: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Executes a promotion plan against Intune.

    Consumes the plan file when one exists (removing it after a fully
    successful run); otherwise plans fresh and applies immediately.
    Deployment state is saved after each applied action, so a failed run
    resumes safely — already-applied actions validate as no-ops.

    Assignment drift is checked on every run — including runs with
    nothing to apply, which therefore still authenticate — and reported
    in the summary, never corrected. Publications whose state writeback
    was lost are recovered first (see
    [reconcile_publications][napt.promote.reconcile.reconcile_publications]).
    When planning fresh, recovery runs before the plan is computed, so a
    recovered release is promotable in the same run; a pre-existing plan
    file was computed earlier and gains nothing from the recovery — the
    next plan run picks the release up.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively.
        state_dir: State directory holding ``deployment/`` and
            ``plan.json``.
        plan_file: Explicit plan file path. When omitted, the default
            plan location is used if present, else a fresh plan is
            computed and applied.
        now: Evaluation clock for ring timestamps and fresh planning.
            Defaults to the current UTC time.

    Returns:
        A summary dict with "applied" and "skipped" action lists,
            "drift" findings, and "recovered" reconciliation findings.

    Raises:
        AuthError: If authentication fails.
        ConfigError: On invalid recipes or unresolvable groups.
        NetworkError: On Graph API failures.
        StateError: On corrupted deployment state or plan file.

    """
    logger = get_global_logger()
    if now is None:
        now = datetime.now(UTC)

    plan_path = plan_file if plan_file is not None else plan_path_for(state_dir)
    deployment_dir = state_dir / "deployment"

    configs = load_recipe_configs(recipes)

    # Authenticate even when there is nothing to apply: the steady state
    # (no eligible promotions) is exactly when out-of-band assignment
    # changes accumulate, so drift is checked on every apply run.
    access_token = get_access_token()
    run = _ApplyRun(access_token, configs, deployment_dir, now)

    # Recover lost publication writebacks before planning, so a
    # recovered release is promotable in this same run.
    recovered = reconcile_publications(
        access_token, configs, deployment_dir, run.existing_apps
    )

    from_file = plan_path.exists()
    if from_file:
        actions = load_plan_file(plan_path)
        logger.info("PROMOTE", f"Applying plan file: {plan_path}")
    else:
        actions = plan_promotions(recipes, state_dir=deployment_dir, now=now)
        logger.info("PROMOTE", "No plan file found; planning and applying")

    for action in actions:
        if action["app_id"] not in configs:
            run.skip(action, "no recipe found for this app")
            continue
        if action["type"] == "assign_install":
            _apply_install_action(run, action)
        else:
            _apply_ring_action(run, action)

    if from_file:
        plan_path.unlink()
        logger.verbose("PROMOTE", f"Consumed plan file: {plan_path}")

    # Drift is checked after the actions so freshly applied assignments
    # are reflected. Findings are warnings only, never corrected.
    drift = detect_drift(access_token, configs, deployment_dir, run.existing_apps)

    return {
        "applied": run.applied,
        "skipped": run.skipped,
        "drift": drift,
        "recovered": recovered,
    }
