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

"""Deployment state persistence for NAPT.

This module implements per-app deployment state: authoritative records of
what NAPT has published to Intune and what is awaiting publication. Unlike
the discovery cache, deployment state is not regenerable.

Each app gets its own file, ``state/deployment/<recipe-id>.json``, so that
concurrent changes to different apps never conflict and each file's diff
is scoped to one app. A file holds four sections:

- ``deployed``: The version currently published to Intune, with its
    SHA-256 hash and Intune app IDs. Null until the first upload.
- ``pending``: The discovered release awaiting publication, with version,
    SHA-256 hash, and download URL. A single slot — a newer discovery
    replaces an unpublished candidate (newest wins). Null when nothing is
    awaiting publication.
- ``rings``: Which version currently holds each deployment ring. Written
    by ``napt promote``.
- ``retained``: Superseded versions kept in Intune for rollback.

Serialization is deterministic (sorted keys, fixed indentation, no
timestamps), so re-running a command that produces no logical change
produces a byte-identical file and a clean git diff.

Example:
    Recording a discovered release:
        ```python
        from pathlib import Path
        from napt.state import (
            deployment_state_path,
            load_deployment_state,
            record_pending,
            save_deployment_state,
        )

        path = deployment_state_path(Path("state/deployment"), "napt-chrome")
        state = load_deployment_state(path)
        action = record_pending(
            state,
            version="130.0.0",
            sha256="abc123...",
            url="https://dl.google.com/chrome.msi",
        )
        if action:
            save_deployment_state(state, path)
        ```

"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from napt.exceptions import PackagingError


def deployment_state_path(state_dir: Path, recipe_id: str) -> Path:
    """Returns the deployment state file path for a recipe.

    Args:
        state_dir: Directory holding per-app deployment state files
            (typically ``state/deployment``).
        recipe_id: Recipe identifier (from recipe's 'id' field).

    Returns:
        Path to the app's deployment state file.

    """
    return state_dir / f"{recipe_id}.json"


def create_default_deployment_state() -> dict[str, Any]:
    """Creates an empty deployment state structure.

    Returns:
        Deployment state with no deployed version, no pending release,
        no ring assignments, and no retained versions.

    """
    return {
        "deployed": None,
        "pending": None,
        "rings": {},
        "retained": [],
    }


def load_deployment_state(state_path: Path) -> dict[str, Any]:
    """Loads deployment state for one app.

    Returns a default empty structure when the file does not exist. Does
    not create the file — deployment state is only written when there is
    something to record.

    Args:
        state_path: Path to the app's deployment state file.

    Returns:
        Deployment state dictionary.

    Raises:
        PackagingError: If the file exists but contains invalid JSON.
            Deployment state is authoritative, so a corrupted file is
            never silently replaced.

    """
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return create_default_deployment_state()
    except json.JSONDecodeError as err:
        raise PackagingError(
            f"Corrupted deployment state file: {state_path}. "
            "Deployment state is authoritative and is not auto-replaced. "
            "Fix the JSON or restore the file from a backup."
        ) from err


def save_deployment_state(state: dict[str, Any], state_path: Path) -> None:
    """Saves deployment state for one app deterministically.

    Creates parent directories if needed. Output is byte-identical for
    logically identical state: keys are sorted, indentation is fixed at
    2 spaces, and no timestamps or run-specific values are written.

    Args:
        state: Deployment state dictionary to save.
        state_path: Path to the app's deployment state file.

    Raises:
        OSError: If the file cannot be written due to permissions.

    """
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git


def record_pending(
    state: dict[str, Any],
    version: str,
    sha256: str,
    url: str,
) -> str | None:
    """Records a discovered release as the pending publication candidate.

    The pending slot holds exactly one candidate and the newest discovery
    wins: a release that differs from both the deployed version and the
    current pending candidate replaces the pending candidate. Identity is
    the SHA-256 hash, not the version string, so a vendor re-release of
    the same version with a different binary is treated as new.

    Args:
        state: Deployment state dictionary to update in place.
        version: Discovered version string.
        sha256: SHA-256 hash of the discovered installer.
        url: Download URL of the discovered installer.

    Returns:
        A string naming the change made ("recorded" for a first candidate,
            "replaced" when a candidate was overwritten, "cleared" when the
            vendor serves the already-deployed release), or
            None when the state did not change.

    """
    deployed = state.get("deployed")
    pending = state.get("pending")

    if deployed and deployed.get("sha256") == sha256:
        # Vendor serves exactly what is deployed; nothing awaits publication.
        if pending is not None:
            state["pending"] = None
            return "cleared"
        return None

    if pending and pending.get("sha256") == sha256:
        return None

    state["pending"] = {
        "version": version,
        "sha256": sha256,
        "url": url,
    }
    return "replaced" if pending else "recorded"


def record_deployed(
    state: dict[str, Any],
    version: str,
    sha256: str,
    intune_app_id: str | None,
    intune_update_app_id: str | None,
) -> None:
    """Records a successful publication as the deployed release.

    Replaces the ``deployed`` section and clears the pending slot when the
    pending candidate is the release that was just published. A pending
    candidate with a different hash (a newer discovery) is left in place.

    Args:
        state: Deployment state dictionary to update in place.
        version: Published version string.
        sha256: SHA-256 hash of the published release's installer.
        intune_app_id: Graph API object ID of the install entry, or None
            when build_types is "update_only".
        intune_update_app_id: Graph API object ID of the update entry, or
            None when build_types is "app_only".

    """
    state["deployed"] = {
        "version": version,
        "sha256": sha256,
        "intune_app_id": intune_app_id,
        "intune_update_app_id": intune_update_app_id,
    }

    pending = state.get("pending")
    if pending and pending.get("sha256") == sha256:
        state["pending"] = None
