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

"""Build manager for PSADT package creation.

Sequences a build from a recipe and a downloaded installer. The steps live
in the modules they belong to:

- [installer][napt.build.installer]: the release to build, the installer
  file whose hash matches it, and what that file says about itself.
- [layout][napt.build.layout]: the versioned build folder, the PSADT
  template and installer copied into it, and the brand pack.
- [commands][napt.build.commands]: the install and uninstall commands for
  MSI and MSIX installers.
- [template][napt.build.template]: the generated Invoke-AppDeployToolkit.ps1.
- [scripts][napt.build.scripts]: the detection and requirements scripts.
- [manifest][napt.build.manifest]: the record left beside the build.

Design Principles:
    - The release to build comes from deployment state; the installer is the
      file in that version's download folder whose SHA-256 matches
    - The installer is read once; every later step uses what was read
    - Entire PSADT Template_v4 structure copied unmodified
    - Invoke-AppDeployToolkit.ps1 is generated from template (not copied)
    - Build directories are versioned: {app_id}/{version}/
    - Branding applied by replacing files in root Assets/ directory (v4 structure)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from napt.build.commands import apply_install_commands
from napt.build.icons import ensure_app_icon
from napt.build.installer import (
    find_installer_file,
    inspect_installer,
    release_to_build,
)
from napt.build.layout import (
    apply_branding,
    copy_installer,
    copy_psadt_template,
    create_build_directory,
    write_build_file,
)
from napt.build.manifest import write_build_manifest
from napt.build.scripts import write_detection_script, write_requirements_script
from napt.build.template import generate_invoke_script
from napt.config.loader import load_effective_config
from napt.logging import get_global_logger
from napt.powershell import PS_SCRIPT_ENCODING
from napt.psadt.release import get_psadt_release


@dataclass(frozen=True)
class BuildResult:
    """Result from building a PSADT package.

    Attributes:
        app_id: Unique application identifier.
        app_name: Application display name.
        version: Application version.
        build_dir: Path to the build directory (packagefiles subdirectory).
        psadt_version: PSADT version used for the build.
    """

    app_id: str
    app_name: str
    version: str
    build_dir: Path
    psadt_version: str


def build_package(
    recipe_path: Path,
    downloads_dir: Path | None = None,
    output_dir: Path | None = None,
    state_dir: Path | None = None,
) -> BuildResult:
    """Builds a PSADT package from a recipe and downloaded installer.

    This is the main entry point for the build process. It:

    1. Loads the recipe configuration
    2. Finds the downloaded installer of the recorded release
    3. Inspects the installer: confirms its version against its folder,
       reads its metadata once, resolves the detection name and
       architecture, and checks an EXE recipe's required fields, all before
       anything is written
    4. Gets/downloads PSADT release
    5. Creates the build directory, copies PSADT unmodified, generates
       Invoke-AppDeployToolkit.ps1 from the template, and copies the
       installer to Files/
    6. Applies custom branding
    7. Generates the detection script (used by the App and Update entries)
    8. Generates the requirements script (when build_types is "both" or
       "update_only")

    Args:
        recipe_path: Path to the recipe YAML file.
        downloads_dir: Directory containing the downloaded
            installer. Default: ``directories.discover`` from config.
        output_dir: Base directory for build output.
            Default: ``directories.build`` from config.
        state_dir: State root whose ``deployment/`` subfolder holds the
            release to build. Default: ``directories.state`` from config.

    Returns:
        Build result naming the app, the version, the packagefiles
            directory, and the PSADT version used.

    Raises:
        ConfigError: If the recipe cannot be loaded or lacks a field the
            installer type needs, or a configured brand pack path does not
            exist.
        PackagingError: If the installer is missing or does not match the
            recorded release, its metadata cannot be read, or a build step
            fails.
        StateError: If the deployment state file is corrupted.
        NetworkError: If the PSADT release cannot be downloaded.

    Example:
        Basic build:
            ```python
            result = build_package(Path("recipes/Google/chrome.yaml"))
            print(result.build_dir)
            # builds/napt-chrome/141.0.7390.123/packagefiles
            ```

        Custom output directory:
            ```python
            result = build_package(
                Path("recipes/Google/chrome.yaml"),
                output_dir=Path("custom/builds")
            )
            ```

    Note:
        Requires installer to be downloaded first (run 'napt discover').
        The version is the name of the download folder, checked against
        the installer's own version for MSI and MSIX.
        Overwrites existing build directory if it exists.
        PSADT files are copied unmodified from cache.
        Invoke-AppDeployToolkit.ps1 is generated (not copied).
        Scripts are generated as siblings to the packagefiles directory
        (not included in .intunewin package - must be uploaded separately to Intune).
        Detection script is always generated.
        The build_types setting controls requirements script only: "both" (default)
        generates detection and requirements, "app_only" generates only detection,
        "update_only" generates detection and requirements.
    """
    logger = get_global_logger()

    logger.step(1, 8, "Loading configuration...")
    config = load_effective_config(recipe_path)
    app_id = config["id"]
    app_name = config["name"]
    if downloads_dir is None:
        downloads_dir = Path(config["directories"]["discover"])
    if output_dir is None:
        output_dir = Path(config["directories"]["build"])

    logger.step(2, 8, "Finding installer...")
    installer_file, installer_sha256 = find_installer_file(
        downloads_dir, app_id, release_to_build(config, state_dir)
    )

    logger.step(3, 8, "Inspecting installer...")
    installer = inspect_installer(installer_file, installer_sha256, config)
    logger.info("BUILD", f"Building {app_name} v{installer.version}")

    # Best-effort: a failed extraction warns and the build continues.
    ensure_app_icon(config, installer.path, app_id)

    logger.step(4, 8, "Getting PSADT release...")
    psadt_config = config["psadt"]
    psadt_cache_dir = get_psadt_release(
        psadt_config["release"], Path(psadt_config["cache_dir"])
    )
    psadt_version = psadt_cache_dir.name  # Directory name is the version
    logger.info("BUILD", f"Using PSADT {psadt_version}")

    logger.step(5, 8, "Creating build structure...")
    build_dir = create_build_directory(output_dir, app_id, installer.version)
    copy_psadt_template(psadt_cache_dir, build_dir)
    apply_install_commands(config, installer)
    invoke_script = generate_invoke_script(
        psadt_cache_dir / "Invoke-AppDeployToolkit.ps1",
        config,
        installer.version,
        psadt_version,
        installer.architecture,
        installer.path.name,
    )
    write_build_file(
        build_dir / "Invoke-AppDeployToolkit.ps1", invoke_script, PS_SCRIPT_ENCODING
    )
    logger.verbose("BUILD", "[OK] Generated Invoke-AppDeployToolkit.ps1")
    copy_installer(installer.path, build_dir)

    logger.step(6, 8, "Applying branding...")
    apply_branding(config, build_dir)

    build_types = config["intune"]["build_types"]

    logger.step(7, 8, "Generating detection script...")
    detection_script_path = write_detection_script(installer, config, build_dir)
    logger.verbose("BUILD", "[OK] Detection script generated")

    requirements_script_path: Path | None = None
    if build_types in ("both", "update_only"):
        logger.step(8, 8, "Generating requirements script...")
        requirements_script_path = write_requirements_script(
            installer, config, build_dir
        )
        logger.verbose("BUILD", "[OK] Requirements script generated")
    else:
        logger.step(8, 8, "Skipping requirements script (build_types=app_only)...")

    write_build_manifest(
        build_dir=build_dir,
        app_id=app_id,
        app_name=app_name,
        version=installer.version,
        build_types=build_types,
        architecture=installer.architecture,
        installer_sha256=installer.sha256,
        detection_script_path=detection_script_path,
        requirements_script_path=requirements_script_path,
    )

    logger.verbose("BUILD", f"[OK] Build complete: {build_dir}")

    return BuildResult(
        app_id=app_id,
        app_name=app_name,
        version=installer.version,
        build_dir=build_dir,
        psadt_version=psadt_version,
    )
