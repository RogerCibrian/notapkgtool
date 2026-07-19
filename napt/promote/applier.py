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

Executes promotion plans against Intune: assigns install entries,
enters and advances releases through rings, displaces superseded
releases, and retires them per the retention policy.

Plans are applied per app: each ``state/plans/<app_id>.json`` file is
an independent unit of work, preflighted, executed, and consumed on
its own. A failure inside one app's plan records the failure, keeps
that plan file for retry, and moves on to the next — one app's broken
group or Graph error never strands the rest of the fleet's
promotions.

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

from napt.exceptions import ConfigError, NetworkError, StateError
from napt.logging import get_global_logger
from napt.promote.drift import detect_drift
from napt.promote.planner import (
    PLAN_SCHEMA_VERSION,
    load_recipe_configs,
    plan_promotions,
    plans_dir_for,
)
from napt.promote.preflight import unresolvable_groups
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
    """Loads planned actions from a per-app plan file.

    Args:
        plan_path: Path to the plan file.

    Returns:
        The planned action dicts.

    Raises:
        StateError: If the plan file contains invalid JSON, lacks an
            actions list, its schemaVersion is missing or unsupported,
            or its actions do not all belong to the single app the file
            declares.

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

    # A plan file is one app's unit of work: apply's failure isolation
    # and consume-after-success semantics attribute the whole file to a
    # single app, so a file mixing apps cannot be applied faithfully.
    action_app_ids = {action.get("app_id") for action in actions}
    declared = data.get("app_id")
    expected = {declared} if declared is not None else action_app_ids
    if len(action_app_ids) > 1 or action_app_ids - expected:
        raise StateError(
            f"Plan file {plan_path} mixes actions for more than one app "
            f"(declared app_id {declared!r}, actions reference "
            f"{sorted(str(a) for a in action_app_ids)}). Plan files are "
            "per-app. Re-run 'napt promote plan' to regenerate them."
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
        self.group_id_cache: dict[str, str] = {}
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
            resolve_assignment_target(self.access_token, group, self.group_id_cache)
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


def _action_skip_reason(run: _ApplyRun, action: dict[str, Any]) -> str | None:
    """Decides whether a planned action would be skipped instead of applied.

    The single authority for skip semantics: the apply loop records the
    returned reason, and the group preflight validates only actions this
    function clears — so a group referenced solely by a stale or
    already-applied action can never block a run. All checks are local
    (state files, cached tenant listing); nothing calls Graph.

    Args:
        run: The apply run context.
        action: The planned action.

    Returns:
        The skip reason, or None when the action should execute.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]
    if app_id not in run.configs:
        return "no recipe found for this app"

    state = run.state_for(app_id)
    deployed = state.get("deployed") or {}
    if deployed.get("sha256") != sha256:
        return "stale action - the deployed release has changed"

    if action["type"] == "assign_install":
        previous = state.get("install_assigned") or {}
        if previous.get("sha256") == sha256:
            return "already applied"
        if find_stamped_app(run.existing_apps, app_id, ENTRY_INSTALL, sha256) is None:
            return "no stamped install entry found in the tenant"
        return None

    ring: str = action["ring"]
    ring_names = [r["name"] for r in run.configs[app_id]["deployment"]["rings"]]
    if ring not in ring_names:
        return f"ring '{ring}' is no longer configured"
    if (state.get("rings") or {}).get(ring, {}).get("sha256") == sha256:
        return "already applied"
    if find_stamped_app(run.existing_apps, app_id, ENTRY_UPDATE, sha256) is None:
        return "no stamped update entry found in the tenant"
    return None


def _apply_ring_action(run: _ApplyRun, action: dict[str, Any]) -> None:
    """Applies an enter_ring or advance_ring action.

    Assumes the action was cleared by
    [_action_skip_reason][napt.promote.applier._action_skip_reason];
    in particular a stamped update entry for the release exists.

    Args:
        run: The apply run context.
        action: The planned action.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]
    ring: str = action["ring"]
    state = run.state_for(app_id)
    rings_state: dict[str, Any] = state.setdefault("rings", {})

    update_app = find_stamped_app(run.existing_apps, app_id, ENTRY_UPDATE, sha256)
    if update_app is None:  # cleared by _action_skip_reason
        run.skip(action, "no stamped update entry found in the tenant")
        return

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


def _apply_install_action(run: _ApplyRun, action: dict[str, Any]) -> None:
    """Applies an assign_install action.

    Assumes the action was cleared by
    [_action_skip_reason][napt.promote.applier._action_skip_reason];
    in particular a stamped install entry for the release exists.

    Args:
        run: The apply run context.
        action: The planned action.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]
    state = run.state_for(app_id)
    previous = state.get("install_assigned") or {}

    install_app = find_stamped_app(run.existing_apps, app_id, ENTRY_INSTALL, sha256)
    if install_app is None:  # cleared by _action_skip_reason
        run.skip(action, "no stamped install entry found in the tenant")
        return

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


def apply_plan(
    recipes: Path,
    state_dir: Path,
    plan_file: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Executes promotion plans against Intune.

    Consumes per-app plan files from ``<state_dir>/plans/`` when any
    exist (removing each after its app applies fully); otherwise plans
    fresh and applies immediately. Each app's plan is an independent
    unit: its groups are preflighted before any of its actions execute,
    so an unresolvable group fails that app with zero mutations — and a
    failure while applying one app records the failure, keeps its plan
    file for retry, and continues with the remaining apps. A dead group
    referenced only by stale or already-applied actions never blocks an
    app. Deployment state is saved after each applied action, so a
    failed run resumes safely — already-applied actions validate as
    no-ops.

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
            ``plans/``.
        plan_file: Explicit path to a single plan file to apply. When
            omitted, every file in the default plans directory is
            applied if any exist, else a fresh plan is computed and
            applied.
        now: Evaluation clock for ring timestamps and fresh planning.
            Defaults to the current UTC time.

    Returns:
        A summary dict with "applied" and "skipped" action lists,
            "failed" per-app failure records (app_id and error),
            "drift" findings, and "recovered" reconciliation findings.

    Raises:
        AuthError: If authentication fails.
        ConfigError: On invalid recipes.
        NetworkError: On Graph API failures outside a per-app unit
            (listing the tenant, reconciliation, the drift check).
        StateError: On corrupted deployment state or plan file.

    """
    logger = get_global_logger()
    if now is None:
        now = datetime.now(UTC)

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

    # Each unit is one app's plan: (plan file to consume, its actions).
    # A fresh plan has no files to consume but keeps the per-app split
    # so failure isolation behaves identically in both modes.
    units: list[tuple[Path | None, list[dict[str, Any]]]]
    if plan_file is not None:
        units = [(plan_file, load_plan_file(plan_file))]
        logger.info("PROMOTE", f"Applying plan file: {plan_file}")
    else:
        plan_paths = sorted(plans_dir_for(state_dir).glob("*.json"))
        if plan_paths:
            units = [(path, load_plan_file(path)) for path in plan_paths]
            logger.info(
                "PROMOTE",
                f"Applying {len(plan_paths)} plan file(s) from "
                f"{plans_dir_for(state_dir)}",
            )
        else:
            fresh = plan_promotions(recipes, state_dir=deployment_dir, now=now)
            by_app: dict[str, list[dict[str, Any]]] = {}
            for action in fresh:
                by_app.setdefault(action["app_id"], []).append(action)
            units = [(None, app_actions) for _, app_actions in sorted(by_app.items())]
            logger.info("PROMOTE", "No plan files found; planning and applying")

    failed: list[dict[str, Any]] = []
    for plan_path, actions in units:
        if plan_path is not None and not actions:
            plan_path.unlink()  # An empty plan file holds no decisions.
            continue
        unit_id = actions[0]["app_id"] if actions else "?"

        # Preflight: every group a live action of this app will touch
        # must resolve before any of its actions execute, so an
        # unresolvable group fails this app with zero mutations instead
        # of stranding a half-applied plan. Skipped actions are excluded
        # — a dead group referenced only by a stale or already-applied
        # action never blocks the app. Resolutions are cached for the
        # action loop below.
        live = [a for a in actions if _action_skip_reason(run, a) is None]
        problems = unresolvable_groups(access_token, live, run.group_id_cache)
        if problems:
            reason = "unresolvable groups: " + "; ".join(problems)
            logger.warning(
                "PROMOTE",
                f"{unit_id}: preflight failed, nothing applied for this "
                f"app; plan kept for retry ({reason})",
            )
            failed.append({"app_id": unit_id, "error": reason})
            continue

        try:
            for action in actions:
                reason = _action_skip_reason(run, action)
                if reason is not None:
                    run.skip(action, reason)
                    continue
                if action["type"] == "assign_install":
                    _apply_install_action(run, action)
                else:
                    _apply_ring_action(run, action)
        except (ConfigError, NetworkError, StateError) as err:
            logger.warning(
                "PROMOTE",
                f"{unit_id}: apply failed, plan kept for retry: {err}",
            )
            failed.append({"app_id": unit_id, "error": str(err)})
            continue

        if plan_path is not None:
            plan_path.unlink()
            logger.verbose("PROMOTE", f"Consumed plan file: {plan_path}")

    # Drift is checked after the actions so freshly applied assignments
    # are reflected. Findings are warnings only, never corrected.
    drift = detect_drift(
        access_token,
        configs,
        deployment_dir,
        run.existing_apps,
        group_id_cache=run.group_id_cache,
    )

    return {
        "applied": run.applied,
        "skipped": run.skipped,
        "failed": failed,
        "drift": drift,
        "recovered": recovered,
    }
