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
promotes releases through rings, displaces the older releases they
replace, and retires them per the retention policy.

Plans are applied per app: each ``state/plans/<app_id>.json`` file is
an independent unit of work, preflighted, executed, and consumed on
its own. Only the plan files of the recipes given to the run are
loaded, so applying one recipe leaves every other app's reviewed plan
in place. A failure inside one app's plan (an unresolvable group, a
Graph error, a state file that cannot be written) records the
failure, keeps that plan file for retry, and moves on to the next;
one app's problem never strands the rest of the fleet's promotions.

Every action is validated against current deployment state before
executing (validate-then-act): stale actions, where the published
release changed since the plan was written or the action already
applied, are skipped with a warning instead of failing, so re-running
apply after a partial failure is safe. Deployment state is saved after
each applied action, and ring ``entered_at`` timestamps are written
here and only here.

Displaced releases are found through their provenance stamps (the
tenant is listed once per run), not through deployment state, which
only records the current release's app IDs. A displaced release that
no longer holds any ring moves to the retained list; releases beyond
``deployment.retain_versions`` have their Intune apps deleted and
leave the run's tenant listing, so the drift check that follows does
not report them.

Assignments NAPT does not manage are preserved: assignment sets are
read, modified, and written back, so admin-made assignments and
non-group targets survive every apply.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from napt.auth.credentials import get_access_token
from napt.exceptions import ConfigError, NetworkError, StateError
from napt.graph.intune import (
    assign_app,
    build_assignment,
    delete_mobile_app,
    get_app_assignments,
    list_mobile_apps,
    resolve_assignment_target,
)
from napt.logging import get_global_logger
from napt.promote.drift import detect_drift
from napt.promote.planner import (
    PLAN_SCHEMA_VERSION,
    load_recipe_configs,
    plans_dir_for,
)
from napt.promote.preflight import unresolvable_groups
from napt.promote.reconcile import reconcile_publications
from napt.state.deployment import (
    deployment_state_path,
    load_deployment_state,
    save_deployment_state,
)
from napt.state.stamp import ENTRY_INSTALL, ENTRY_UPDATE, find_stamped_app

# Ring assignments target the Update entry, which is gated to devices
# with an older release installed: always a required install.
_RING_INTENT = "required"

# Fields every planned action carries, and the one field each type adds.
_ACTION_FIELDS = {"sha256": str, "version": str, "groups": list}
_ACTION_TYPE_FIELDS = {"assign": ("intent", str), "promote": ("ring", str)}


def _corrupted(plan_path: Path, problem: str) -> StateError:
    """Builds the error for a plan file that does not match the planner's output."""
    return StateError(
        f"Corrupted plan file: {plan_path}. {problem}. "
        "Re-run 'napt promote plan' to regenerate it."
    )


def _check_action(action: Any, index: int, plan_path: Path) -> None:
    """Verifies that one plan action has the shape the planner writes.

    Args:
        action: The raw action from the plan file.
        index: One-based position of the action in the file, for the
            error message.
        plan_path: Path to the plan file, for the error message.

    Raises:
        StateError: If the action is not an object, has an unknown type,
            or is missing a field apply keys on.

    """
    if not isinstance(action, dict):
        raise _corrupted(plan_path, f"action {index} is not an object")
    action_type = action.get("type")
    if action_type not in _ACTION_TYPE_FIELDS:
        raise _corrupted(
            plan_path,
            f"action {index} has unknown type {action_type!r} (expected "
            f"{' or '.join(sorted(_ACTION_TYPE_FIELDS))})",
        )
    required = dict(_ACTION_FIELDS)
    key, kind = _ACTION_TYPE_FIELDS[action_type]
    required[key] = kind
    for field, expected in required.items():
        if not isinstance(action.get(field), expected):
            raise _corrupted(
                plan_path,
                f"action {index} is missing '{field}' or it is not "
                f"{'a list' if expected is list else 'a string'}",
            )
    if not all(isinstance(group, str) for group in action["groups"]):
        raise _corrupted(plan_path, f"action {index} has a non-string group")


def load_plan_file(plan_path: Path) -> list[dict[str, Any]]:
    """Loads planned actions from a per-app plan file.

    The file records its app id and display name once at the top level;
    both are re-injected into every returned action, so in-memory
    actions look the same as the planner's output. The filename is the
    app's identity, as for deployment state: ``<app_id>.json`` must
    declare that same app id.

    Args:
        plan_path: Path to the plan file.

    Returns:
        The planned action dicts.

    Raises:
        StateError: If the plan file cannot be read, contains invalid
            JSON, lacks an actions list or app id, declares an app id
            other than its filename, its schemaVersion is missing or
            unsupported, an action is not shaped like the planner writes
            it, or an action references a different app than the one
            the file declares.

    """
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError as err:
        raise StateError(f"Cannot read plan file {plan_path}: {err}") from err
    try:
        data = json.loads(text)
        actions = data["actions"]
        declared = data["app_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as err:
        raise StateError(
            f"Corrupted plan file: {plan_path}. "
            "Re-run 'napt promote plan' to regenerate it."
        ) from err
    if not isinstance(actions, list):
        raise _corrupted(plan_path, "'actions' is not a list")
    if not isinstance(declared, str):
        raise _corrupted(plan_path, "'app_id' is not a string")
    if declared != plan_path.stem:
        raise StateError(
            f"Plan file {plan_path} declares app_id {declared!r}, but its "
            f"filename says {plan_path.stem!r}. The file was likely copied "
            "or renamed. Fix whichever is wrong before continuing."
        )

    found = data.get("schemaVersion")
    if found != PLAN_SCHEMA_VERSION:
        raise StateError(
            f"Unsupported plan schema version {found!r} in {plan_path} "
            f"(this NAPT release supports version {PLAN_SCHEMA_VERSION}). "
            "Re-run 'napt promote plan' to regenerate it."
        )

    for index, action in enumerate(actions, start=1):
        _check_action(action, index, plan_path)

    # A plan file is one app's unit of work: apply's failure isolation
    # and consume-after-success semantics attribute the whole file to a
    # single app, so a file whose actions reference another app (a hand
    # edit) cannot be applied faithfully.
    foreign = {
        action.get("app_id")
        for action in actions
        if action.get("app_id") not in (None, declared)
    }
    if foreign:
        raise StateError(
            f"Plan file {plan_path} mixes actions for more than one app "
            f"(declared app_id {declared!r}, actions reference "
            f"{sorted(str(a) for a in foreign)}). Plan files are "
            "per-app. Re-run 'napt promote plan' to regenerate them."
        )

    name = data.get("name")
    for action in actions:
        action["app_id"] = declared
        if name is not None:
            action.setdefault("name", name)
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
        """Persists an app's deployment state after an applied action.

        Raises:
            StateError: If the state file cannot be written. Intune has
                already been changed at this point; the message says so
                and that re-running apply repeats the action safely
                (assignments are replaced, not duplicated, and retention
                works from a fresh tenant listing).

        """
        state = self._states[app_id]
        state["name"] = self.configs[app_id]["name"]
        state_path = deployment_state_path(self.deployment_dir, app_id)
        try:
            save_deployment_state(state, state_path)
        except OSError as err:
            raise StateError(
                f"{app_id}: Intune was updated but deployment state could "
                f"not be written to {state_path}: {err}. Fix the file or "
                "its permissions and re-run apply; the action is repeated "
                "safely"
            ) from err

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

    The release joins the retained list as its newest entry; a release
    displaced for a second time (rolled back to, then superseded again)
    moves to the end rather than keeping its old position, so the
    ordering stays oldest first. Releases beyond
    ``deployment.retain_versions`` have their stamped Intune apps
    deleted, oldest first. The currently published release is never
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

    retained[:] = [entry for entry in retained if entry.get("sha256") != sha256]
    retained.append({"version": version, "sha256": sha256})
    logger.info(
        "PROMOTE",
        f"{app_id}: retained displaced release {version} for rollback",
    )

    retain_limit: int = run.configs[app_id]["deployment"]["retain_versions"]
    published = state.get("published") or {}
    while len(retained) > retain_limit:
        oldest = retained.pop(0)
        if oldest.get("sha256") == published.get("sha256"):
            continue  # Never delete the currently published release.
        for entry_type in (ENTRY_INSTALL, ENTRY_UPDATE):
            app = find_stamped_app(
                run.existing_apps, app_id, entry_type, oldest["sha256"]
            )
            if app is not None:
                delete_mobile_app(run.access_token, app["id"])
                # The drift check runs on this listing after the actions;
                # a deleted entry must not be reported as orphaned.
                run.existing_apps.remove(app)
                logger.info(
                    "PROMOTE",
                    f"{app_id}: deleted retired {entry_type} entry "
                    f"{oldest.get('version')} ({app['id']})",
                )


def _action_skip_reason(run: _ApplyRun, action: dict[str, Any]) -> str | None:
    """Decides whether a planned action would be skipped instead of applied.

    The single authority for skip semantics: the apply loop records the
    returned reason, and the group preflight validates only actions this
    function clears, so a group referenced solely by a stale or
    already-applied action can never block a run. All checks are local
    (state files, cached tenant listing); nothing calls Graph. The
    action's app is one of the run's recipes: apply loads no other
    plan files.

    Args:
        run: The apply run context.
        action: The planned action.

    Returns:
        The skip reason, or None when the action should execute.

    """
    app_id: str = action["app_id"]
    sha256: str = action["sha256"]

    state = run.state_for(app_id)
    published = state.get("published") or {}
    if published.get("sha256") != sha256:
        return "stale action - the published release has changed"

    if action["type"] == "assign":
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


def _apply_promote(run: _ApplyRun, action: dict[str, Any]) -> None:
    """Applies a promote action, assigning the update entry to its target ring.

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


def _apply_assign(run: _ApplyRun, action: dict[str, Any]) -> None:
    """Applies an assign action, pointing the install entry at the release.

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

    Consumes the given recipes' plan files from ``<state_dir>/plans/``,
    removing each after its app applies fully. A plan file written by
    ``napt promote plan`` is the only thing apply executes: a recipe
    without one has nothing to apply, and plan files for apps outside
    the run are left untouched, so applying one recipe never consumes
    another app's reviewed plan. Each app's plan is an independent
    unit: its groups are preflighted before any of its actions execute,
    so an unresolvable group fails that app with zero mutations, and a
    failure while preflighting or applying one app records the
    failure, keeps its plan file for retry, and continues with the
    remaining apps. A dead group referenced only by stale or
    already-applied actions never blocks an app. Deployment state is
    saved after each applied action, so a failed run resumes safely:
    already-applied actions validate as no-ops.

    Assignment drift is checked on every run, including runs with
    nothing to apply (which therefore still authenticate), and reported
    in the summary, never corrected. Publications whose state writeback
    was lost are recovered first (see
    [reconcile_publications][napt.promote.reconcile.reconcile_publications]);
    a recovered release is picked up by the next plan run, since the
    plan files being applied were computed before the recovery.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively.
        state_dir: State directory holding ``deployment/`` and
            ``plans/``.
        plan_file: Explicit path to a single plan file to apply; its app
            must be one of the recipes. When omitted, the recipes' plan
            files in the default plans directory are applied.
        now: Evaluation clock for ring timestamps. Defaults to the
            current UTC time.

    Returns:
        A summary dict with "applied" and "skipped" action lists,
            "failed" per-app failure records (app_id and error),
            "drift" findings, and "recovered" reconciliation findings.

    Raises:
        AuthError: If authentication fails, or Graph rejects the token
            during a run.
        ConfigError: On invalid recipes, or a plan file for an app the
            run has no recipe for.
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

    # Recover lost publication writebacks so state is right for the
    # actions below and for the next plan run.
    recovered = reconcile_publications(
        access_token, configs, deployment_dir, run.existing_apps
    )

    # Each unit is one app's plan: (plan file to consume, its actions).
    # The filename is the app's identity (load_plan_file rejects a file
    # whose declared app id disagrees), so the stem decides which files
    # belong to this run before any content is read.
    units: list[tuple[Path, list[dict[str, Any]]]]
    if plan_file is not None:
        if plan_file.stem not in configs:
            raise ConfigError(
                f"Plan file {plan_file} is for app '{plan_file.stem}', which "
                f"is not among the recipes given ({recipes}). Pass that "
                "app's recipe, or the recipes directory."
            )
        units = [(plan_file, load_plan_file(plan_file))]
        logger.info("PROMOTE", f"Applying plan file: {plan_file}")
    else:
        plan_paths = sorted(plans_dir_for(state_dir).glob("*.json"))
        outside = [path for path in plan_paths if path.stem not in configs]
        if outside:
            logger.info(
                "PROMOTE",
                f"Left {len(outside)} plan file(s) for apps outside this run "
                f"untouched: {', '.join(path.stem for path in outside)}",
            )
        mine = [path for path in plan_paths if path.stem in configs]
        units = [(path, load_plan_file(path)) for path in mine]
        if mine:
            logger.info(
                "PROMOTE",
                f"Applying {len(mine)} plan file(s) from {plans_dir_for(state_dir)}",
            )
        else:
            logger.info(
                "PROMOTE",
                "No plan files to apply; run 'napt promote plan' to compute them",
            )

    failed: list[dict[str, Any]] = []
    for plan_path, actions in units:
        if not actions:
            plan_path.unlink()  # An empty plan file holds no decisions.
            continue
        unit_id = plan_path.stem

        # Preflight: every group a live action of this app will touch
        # must resolve before any of its actions execute, so an
        # unresolvable group fails this app with zero mutations instead
        # of stranding a half-applied plan. Skipped actions are excluded:
        # a dead group referenced only by a stale or already-applied
        # action never blocks the app. Resolutions are cached for the
        # action loop below. The preflight's own Graph calls sit inside
        # the same per-app isolation as the actions, so a transient
        # failure there fails this app only; a rejected token (AuthError)
        # still aborts the run, since it would fail every app the same
        # way.
        try:
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

            for action in actions:
                reason = _action_skip_reason(run, action)
                if reason is not None:
                    run.skip(action, reason)
                    continue
                if action["type"] == "assign":
                    _apply_assign(run, action)
                else:
                    _apply_promote(run, action)
        except (ConfigError, NetworkError, StateError) as err:
            logger.warning(
                "PROMOTE",
                f"{unit_id}: apply failed, plan kept for retry: {err}",
            )
            failed.append({"app_id": unit_id, "error": str(err)})
            continue

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
