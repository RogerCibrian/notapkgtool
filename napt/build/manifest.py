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

"""The build manifest: what a build records about itself for later stages.

``napt build`` writes ``build-manifest.json`` beside ``packagefiles/``.
``napt package`` reads it to verify the build and copies it into the
package folder with the .intunewin name and hash added; ``napt upload``
reads that copy. The key names live here so every stage spells them the
same way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from napt.exceptions import PackagingError
from napt.files import write_text_atomic
from napt.logging import get_global_logger

MANIFEST_NAME = "build-manifest.json"


def write_build_manifest(
    build_dir: Path,
    app_id: str,
    app_name: str,
    version: str,
    build_types: str,
    architecture: str,
    installer_sha256: str,
    detection_script_path: Path,
    requirements_script_path: Path | None,
) -> Path:
    """Writes the build manifest beside the packagefiles folder.

    Args:
        build_dir: Build directory (packagefiles subdirectory).
        app_id: Application ID.
        app_name: Application display name.
        version: Application version.
        build_types: The build_types setting used ("both", "app_only",
            "update_only").
        architecture: Resolved installer architecture ("x86", "x64",
            "arm64", "any"): from the installer for MSI and MSIX, from the
            recipe for EXE.
        installer_sha256: SHA-256 hex digest of the source installer file,
            carried through so 'napt upload' can verify provenance.
        detection_script_path: The detection script.
        requirements_script_path: The requirements script, or None when
            build_types is "app_only".

    Returns:
        Path to the written manifest.

    Raises:
        PackagingError: If the manifest cannot be written.
    """
    manifest: dict[str, Any] = {
        "app_id": app_id,
        "app_name": app_name,
        "version": version,
        "win32_build_types": build_types,
        "architecture": architecture,
        "installer_sha256": installer_sha256,
        # Script names only, so the manifest stays valid wherever the build
        # folder is moved to.
        "detection_script_path": detection_script_path.name,
    }
    if requirements_script_path is not None:
        manifest["requirements_script_path"] = requirements_script_path.name

    manifest_path = build_dir.parent / MANIFEST_NAME
    try:
        write_text_atomic(manifest_path, json.dumps(manifest, indent=2) + "\n")
    except OSError as err:
        raise PackagingError(f"Cannot write {manifest_path}: {err}") from err
    get_global_logger().verbose("BUILD", f"Build manifest written to: {manifest_path}")
    return manifest_path


def read_build_manifest(
    directory: Path, required: tuple[str, ...], remedy: str
) -> dict[str, Any]:
    """Reads a build manifest and checks the keys the caller relies on.

    Args:
        directory: The folder holding ``build-manifest.json``: the build's
            version directory, or the package directory it was copied to.
        required: Keys that must be present as non-empty strings.
        remedy: What to run to get a good manifest, appended to every
            error message.

    Returns:
        The parsed manifest.

    Raises:
        PackagingError: If the manifest is missing, not JSON, not an
            object, or lacks a required key.
    """
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise PackagingError(f"Build manifest not found: {manifest_path}. {remedy}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise PackagingError(
            f"Cannot read {MANIFEST_NAME} in {directory}: {err}. {remedy}"
        ) from err
    if not isinstance(manifest, dict):
        raise PackagingError(
            f"{MANIFEST_NAME} in {directory} is not a JSON object. {remedy}"
        )
    for key in required:
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise PackagingError(
                f"{MANIFEST_NAME} in {directory} has no {key}. {remedy}"
            )
    return manifest
