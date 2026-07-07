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

"""Promotion planning for NAPT deployment rings.

Computes promotion actions as a pure function of (deployment state,
configuration, clock) — no Graph calls, no side effects beyond the plan
file. Re-running plan against unchanged inputs produces byte-identical
output, so committed plan files diff cleanly and CI can use the plan
file's change status to decide whether to open a review.

Three action types are planned per app:

- ``assign_install``: The install entry has never been assigned; assign
    it to the configured ``deployment.install`` groups.
- ``enter_ring``: The deployed release holds no ring; assign the Update
    entry to the first ring's groups.
- ``advance_ring``: The deployed release has held its furthest ring for
    at least that ring's ``promote_after_days``; assign the next ring.

A ring without ``promote_after_days`` never advances automatically —
releases hold it until the configuration changes (the natural terminal
ring, or a deliberate manual gate).

The plan file (default ``state/plan.json``) is written only when actions
exist; a stale plan file is removed when a plan run finds none. Exit
codes follow NAPT's uniform contract (0 success, 1 error) — CI detects
pending work from the plan file's git status, not from exit codes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from napt.config import load_effective_config
from napt.exceptions import ConfigError, StateError
from napt.logging import get_global_logger
from napt.state import deployment_state_path, load_deployment_state

__all__ = [
    "plan_path_for",
    "plan_promotions",
    "resolve_state_dir",
    "write_plan_file",
]

# Deterministic ordering of action types within one app's actions.
_ACTION_ORDER = {"assign_install": 0, "enter_ring": 1, "advance_ring": 2}


def plan_path_for(state_dir: Path) -> Path:
    """Returns the plan file path for a state directory.

    Args:
        state_dir: The configured state directory (``directories.state``).

    Returns:
        Path to the plan file (``<state_dir>/plan.json``).

    """
    return state_dir / "plan.json"


def _parse_entered_at(value: str, context: str) -> datetime:
    """Parses a ring entry timestamp from deployment state.

    Args:
        value: ISO-8601 timestamp string written by promote apply.
        context: Field description for error messages.

    Returns:
        The parsed timezone-aware datetime.

    Raises:
        StateError: If the timestamp cannot be parsed.

    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as err:
        raise StateError(
            f"{context}: invalid entered_at timestamp {value!r} in "
            "deployment state. Fix the JSON or restore the file from a backup."
        ) from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _plan_app_actions(
    config: dict[str, Any],
    state: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    """Computes promotion actions for one app.

    Args:
        config: Effective configuration for the app's recipe.
        state: The app's deployment state.
        now: The evaluation clock (timezone-aware).

    Returns:
        Action dicts for this app, in deterministic order. Empty when
            nothing is eligible.

    """
    app_id: str = config["id"]
    deployment: dict[str, Any] = config["deployment"]
    deployed = state.get("deployed")

    if not deployed:
        return []

    actions: list[dict[str, Any]] = []
    version: str = deployed["version"]
    sha256: str = deployed["sha256"]

    # Install entry: assigned once per release, when groups are configured.
    # install_assigned records the release (version + sha256) whose install
    # entry currently carries the assignment, so a new release plans a
    # fresh assignment (and apply displaces the old one).
    install_cfg: dict[str, Any] = deployment["install"]
    install_assigned = state.get("install_assigned") or {}
    if (
        deployed.get("intune_app_id")
        and install_cfg["groups"]
        and install_assigned.get("sha256") != sha256
    ):
        actions.append(
            {
                "type": "assign_install",
                "app_id": app_id,
                "version": version,
                "sha256": sha256,
                "intent": install_cfg["intent"],
                "groups": list(install_cfg["groups"]),
            }
        )

    # Update entry: rides the rings.
    rings_cfg: list[dict[str, Any]] = deployment["rings"]
    if not rings_cfg or not deployed.get("intune_update_app_id"):
        return actions

    rings_state: dict[str, Any] = state.get("rings", {})
    ring_names = [ring["name"] for ring in rings_cfg]
    held_indexes = [
        index
        for index, name in enumerate(ring_names)
        if rings_state.get(name, {}).get("sha256") == sha256
    ]

    if not held_indexes:
        first = rings_cfg[0]
        actions.append(
            {
                "type": "enter_ring",
                "app_id": app_id,
                "version": version,
                "sha256": sha256,
                "ring": first["name"],
                "groups": list(first["groups"]),
            }
        )
        return actions

    furthest = max(held_indexes)
    if furthest + 1 >= len(rings_cfg):
        return actions  # Already at the final ring.

    days = rings_cfg[furthest].get("promote_after_days")
    if days is None:
        return actions  # This ring only advances manually.

    held_ring_name = ring_names[furthest]
    entered_at = _parse_entered_at(
        rings_state[held_ring_name].get("entered_at"),
        f"{app_id}: rings.{held_ring_name}",
    )
    if now - entered_at < timedelta(days=days):
        return actions  # Still baking.

    next_ring = rings_cfg[furthest + 1]
    actions.append(
        {
            "type": "advance_ring",
            "app_id": app_id,
            "version": version,
            "sha256": sha256,
            "from_ring": held_ring_name,
            "ring": next_ring["name"],
            "groups": list(next_ring["groups"]),
        }
    )
    return actions


def _collect_recipe_paths(recipes: Path) -> list[Path]:
    """Collects recipe file paths from a file or directory.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively
            for ``*.yaml`` / ``*.yml`` files.

    Returns:
        Sorted recipe file paths.

    Raises:
        ConfigError: If the path does not exist or contains no recipes.

    """
    if recipes.is_file():
        return [recipes]
    if recipes.is_dir():
        found = sorted(
            path for pattern in ("*.yaml", "*.yml") for path in recipes.rglob(pattern)
        )
        if not found:
            raise ConfigError(f"No recipe files found under {recipes}")
        return found
    raise ConfigError(f"Recipe path not found: {recipes}")


def resolve_state_dir(recipes: Path) -> Path:
    """Resolves the configured state directory for a plan run.

    ``directories.state`` is org policy — consistent across a project —
    so the first recipe's effective configuration determines it for a
    fleet-wide run.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively.

    Returns:
        The configured state directory.

    Raises:
        ConfigError: If the recipes path is invalid or the first recipe
            cannot be loaded.

    """
    first = _collect_recipe_paths(recipes)[0]
    config = load_effective_config(first)
    return Path(config["directories"]["state"])


def plan_promotions(
    recipes: Path,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Computes promotion actions for a recipe or a directory of recipes.

    Loads each recipe's effective configuration, reads its deployment
    state, and evaluates ring eligibility against the clock. Read-only:
    neither Intune nor the state files are modified.

    Args:
        recipes: A recipe YAML file, or a directory scanned recursively.
        state_dir: Directory holding per-app deployment state files.
            When omitted, each recipe's ``directories.state`` setting is
            used (``<state>/deployment``).
        now: Evaluation clock. Defaults to the current UTC time; tests
            pass a fixed value for determinism.

    Returns:
        Action dicts sorted by app id and action type.

    Raises:
        ConfigError: On invalid recipes or an invalid recipes path.
        StateError: On a corrupted deployment state file or an invalid
            ring timestamp.

    """
    logger = get_global_logger()
    if now is None:
        now = datetime.now(UTC)

    actions: list[dict[str, Any]] = []
    for recipe_path in _collect_recipe_paths(recipes):
        config = load_effective_config(recipe_path)
        app_state_dir = (
            state_dir
            if state_dir is not None
            else Path(config["directories"]["state"]) / "deployment"
        )
        state = load_deployment_state(
            deployment_state_path(app_state_dir, config["id"])
        )
        app_actions = _plan_app_actions(config, state, now)
        if app_actions:
            logger.verbose(
                "PROMOTE",
                f"{config['id']}: {len(app_actions)} action(s) planned",
            )
        actions.extend(app_actions)

    actions.sort(key=lambda a: (a["app_id"], _ACTION_ORDER[a["type"]]))
    return actions


def write_plan_file(actions: list[dict[str, Any]], plan_path: Path) -> bool:
    """Writes the plan file, or removes a stale one when there is no work.

    The plan file exists exactly when there are planned actions, so its
    git status is the signal that a promotion review is needed. Output is
    deterministic (sorted keys, fixed indentation, no timestamps).

    Args:
        actions: Planned actions from plan_promotions.
        plan_path: Path to the plan file.

    Returns:
        True when a plan file exists after the call, False when there
            was no work (and any stale plan file was removed).

    """
    if not actions:
        if plan_path.exists():
            plan_path.unlink()
        return False

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"actions": actions}, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git
    return True
