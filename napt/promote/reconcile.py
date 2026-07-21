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

"""Publication recovery for lost deployment state writebacks.

A publish run records the pending-to-published transition in deployment
state after uploading, but that record can be lost — most commonly when
a CI runner uploads successfully and then fails to push the state commit
(branch protection, network). The tenant then holds a fully published
release that state still lists as pending, which blocks promotion
planning and, if a newer discovery replaces the pending slot, orphans
the published release permanently.

Reconciliation closes that gap by re-deriving the record from tenant
evidence: when every entry the app's ``build_types`` requires exists in
Intune, stamped for the pending release's installer hash and with
committed content, the publication demonstrably succeeded and
``published`` is recorded exactly as the publish run would have. This
trusts provenance stamps and committed content the same way idempotent
upload adoption already does — no new trust is introduced.

Unlike drift detection, which never corrects, reconciliation writes
deployment state: it completes NAPT's own half-persisted transaction
rather than overriding an admin's tenant change.

Finding kinds:

- ``recovered``: The publication was fully committed in the tenant and
    has been recorded as published.
- ``incomplete``: Some required entries are missing or their content was
    never committed; nothing is recorded — re-run publish to finish.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from napt.logging import get_global_logger
from napt.state import (
    deployment_state_path,
    load_deployment_state,
    record_published,
    save_deployment_state,
)
from napt.upload.graph import get_mobile_app
from napt.upload.stamp import ENTRY_INSTALL, ENTRY_UPDATE, find_stamped_app

__all__ = ["reconcile_publications"]

_REQUIRED_ENTRIES = {
    "both": (ENTRY_INSTALL, ENTRY_UPDATE),
    "app_only": (ENTRY_INSTALL,),
    "update_only": (ENTRY_UPDATE,),
}


def reconcile_publications(
    access_token: str,
    configs: dict[str, dict[str, Any]],
    deployment_dir: Path,
    existing_apps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Records publications whose deployment state writeback was lost.

    For each app with a pending release, checks the tenant for stamped
    entries matching the pending installer hash. When every entry
    required by the app's ``build_types`` exists with committed content,
    records the release as published (clearing the pending slot) exactly
    as the original publish run would have. Partial evidence — some
    entries missing or uncommitted — is warned about but never recorded,
    because only a publish re-run can finish the upload.

    Apps whose pending release has no stamped entries at all are the
    normal awaiting-publication case and produce no finding.

    Args:
        access_token: Bearer token for Graph API.
        configs: Effective configurations keyed by recipe id.
        deployment_dir: Directory holding per-app deployment state files.
        existing_apps: Mobile app dicts from list_mobile_apps.

    Returns:
        Finding dicts, each with "app_id", "kind" ("recovered" or
            "incomplete"), and "detail" keys, sorted for deterministic
            output. Empty when no pending release has tenant evidence.

    Raises:
        AuthError: On 401 or 403.
        NetworkError: On Graph API failures.
        StateError: On a corrupted deployment state file.

    """
    logger = get_global_logger()
    findings: list[dict[str, Any]] = []

    for app_id, config in configs.items():
        state_path = deployment_state_path(deployment_dir, app_id)
        state = load_deployment_state(state_path)
        pending = state.get("pending")
        if not pending:
            continue

        sha256 = pending["sha256"]
        required = _REQUIRED_ENTRIES[config["intune"]["build_types"]]
        matches = {
            entry: find_stamped_app(existing_apps, app_id, entry, sha256)
            for entry in required
        }
        if not any(matches.values()):
            continue  # Never published; a normal pending release.

        problems: list[str] = []
        for entry, match in matches.items():
            if match is None:
                problems.append(f"no stamped {entry} entry exists")
                continue
            full_app = get_mobile_app(access_token, match["id"])
            if not full_app.get("committedContentVersion"):
                problems.append(f"the {entry} entry's content was never committed")

        version = pending["version"]
        if problems:
            detail = (
                f"pending release {version} ({sha256[:12]}) was partially "
                f"published: {'; '.join(problems)} - re-run publish to finish"
            )
            logger.warning("PROMOTE", f"{app_id}: {detail}")
            findings.append(
                {"app_id": app_id, "kind": "incomplete", "detail": detail}
            )
            continue

        install_match = matches.get(ENTRY_INSTALL)
        update_match = matches.get(ENTRY_UPDATE)
        record_published(
            state,
            version=version,
            sha256=sha256,
            intune_app_id=install_match["id"] if install_match else None,
            intune_update_app_id=update_match["id"] if update_match else None,
        )
        state["name"] = config["name"]
        save_deployment_state(state, state_path)
        detail = (
            f"recorded publication of {version} ({sha256[:12]}): all entries "
            "are committed in the tenant but the published record was missing"
        )
        logger.info("PROMOTE", f"{app_id}: {detail}")
        findings.append({"app_id": app_id, "kind": "recovered", "detail": detail})

    findings.sort(key=lambda f: (f["app_id"], f["kind"], f["detail"]))
    return findings
