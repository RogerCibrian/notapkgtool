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

"""The build folder and what goes into it.

Creates ``builds/<id>/<version>/packagefiles/``, copies the PSADT template
and the installer into it, applies the brand pack, and writes generated
files with a failure reported by path.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from napt.exceptions import ConfigError, PackagingError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component


def write_build_file(path: Path, text: str, encoding: str) -> None:
    """Writes a generated build file, reporting a refused write by path.

    Args:
        path: Where to write.
        text: The file's content.
        encoding: Text encoding; generated scripts use
            ``PS_SCRIPT_ENCODING``.

    Raises:
        PackagingError: If the file cannot be written.
    """
    try:
        path.write_text(text, encoding=encoding)
    except OSError as err:
        raise PackagingError(f"Cannot write {path}: {err}") from err


def create_build_directory(base_dir: Path, app_id: str, version: str) -> Path:
    """Creates the build directory structure.

    Creates ``{base_dir}/{app_id}/{version}/packagefiles/``, replacing an
    existing build of that version. The packagefiles/ subdirectory holds
    the PSADT files that are packaged into the .intunewin file; detection
    scripts are saved as its siblings so they stay out of the package.

    Args:
        base_dir: Base builds directory.
        app_id: Application ID.
        version: Application version.

    Returns:
        Path to the packagefiles subdirectory where PSADT files will be copied
            (build_dir/packagefiles/).

    Raises:
        PackagingError: If the version cannot be used as a folder name, or
            the directory cannot be created.
    """
    logger = get_global_logger()
    # An existing build directory is deleted below, so whatever names it must
    # never be allowed to point that delete somewhere else.
    if not is_safe_path_component(version):
        raise PackagingError(
            f"Version {version!a} for {app_id} cannot be used as a folder name. "
            "Versions may contain only letters, digits, '.', '-', '_', and '+'."
        )
    version_dir = base_dir / app_id / version
    packagefiles_dir = version_dir / "packagefiles"

    try:
        if version_dir.exists():
            logger.verbose("BUILD", f"Build directory exists: {version_dir}")
            logger.verbose("BUILD", "Removing existing build...")
            shutil.rmtree(version_dir)
        packagefiles_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise PackagingError(
            f"Cannot create build directory {packagefiles_dir}: {err}"
        ) from err

    logger.verbose("BUILD", f"Created build directory: {packagefiles_dir}")
    return packagefiles_dir


def copy_psadt_template(psadt_cache_dir: Path, build_dir: Path) -> None:
    """Copies the PSADT template from the cache into the build unmodified.

    Copies the entire v4 template structure: PSAppDeployToolkit/ (module),
    Invoke-AppDeployToolkit.exe, Invoke-AppDeployToolkit.ps1 (the template,
    overwritten by the generated script), Assets/, Config/, Strings/,
    Files/, SupportFiles/, and PSAppDeployToolkit.Extensions/.

    Args:
        psadt_cache_dir: Path to cached PSADT version directory (root
            of Template_v4 extraction).
        build_dir: Build directory (packagefiles subdirectory) where PSADT
            should be copied.

    Raises:
        PackagingError: If PSADT cache directory or required files don't
            exist, or the copy fails.
    """
    logger = get_global_logger()
    if not psadt_cache_dir.exists():
        raise PackagingError(f"PSADT cache directory not found: {psadt_cache_dir}")

    logger.verbose("BUILD", f"Copying PSADT template from cache: {psadt_cache_dir}")

    try:
        for item in psadt_cache_dir.iterdir():
            dest = build_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
                logger.verbose("BUILD", f"  Copied directory: {item.name}/")
            else:
                shutil.copy2(item, dest)
                logger.verbose("BUILD", f"  Copied file: {item.name}")
    except OSError as err:
        raise PackagingError(
            f"Cannot copy the PSADT template into {build_dir}: {err}"
        ) from err

    logger.verbose("BUILD", "[OK] PSADT template copied")


def copy_installer(installer_file: Path, build_dir: Path) -> None:
    """Copies the installer to the build's Files/ directory.

    Args:
        installer_file: Path to the installer file.
        build_dir: Build directory (packagefiles subdirectory).

    Raises:
        PackagingError: If the copy fails.
    """
    logger = get_global_logger()
    files_dir = build_dir / "Files"
    dest = files_dir / installer_file.name

    logger.verbose("BUILD", f"Copying installer: {installer_file.name}")

    try:
        shutil.copy2(installer_file, dest)
    except OSError as err:
        raise PackagingError(
            f"Cannot copy installer {installer_file.name} to {files_dir}: {err}"
        ) from err

    logger.verbose("BUILD", "[OK] Installer copied to Files/")


def apply_branding(config: dict[str, Any], build_dir: Path) -> None:
    """Replaces PSADT's default assets with the configured brand pack.

    Each mapping copies the first file matching its ``source`` glob to its
    ``target`` under the build, keeping the source file's extension. A
    mapping whose glob matches nothing leaves the default asset in place.

    Args:
        config: Merged configuration with brand_pack settings.
        build_dir: Build directory (packagefiles subdirectory) containing
            PSAppDeployToolkit/.

    Raises:
        ConfigError: If the configured ``brand_pack.path`` does not exist.
        PackagingError: If a brand asset cannot be copied.
    """
    logger = get_global_logger()
    brand_pack = config["psadt"]["brand_pack"]

    if not brand_pack["path"]:
        logger.verbose("BUILD", "No brand pack configured, using PSADT defaults")
        return

    brand_path = Path(brand_pack["path"])
    if not brand_path.is_dir():
        raise ConfigError(
            f"psadt.brand_pack.path {brand_path} does not exist. Fix the path "
            "or remove the brand pack to build with PSADT's default assets."
        )

    logger.verbose("BUILD", f"Applying branding from: {brand_path}")

    for mapping in brand_pack["mappings"]:
        source_pattern = mapping["source"]
        source_files = list(brand_path.glob(source_pattern))
        if not source_files:
            logger.verbose("BUILD", f"No files match pattern: {source_pattern}")
            continue

        # The target is written without an extension; the source's is kept.
        source_file = source_files[0]
        target = build_dir / mapping["target"]
        target_with_ext = Path(str(target) + source_file.suffix)

        try:
            target_with_ext.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_with_ext)
        except OSError as err:
            raise PackagingError(
                f"Cannot copy brand asset {source_file.name} to "
                f"{target_with_ext}: {err}"
            ) from err
        logger.verbose("BUILD", f"  {source_file.name} -> {target_with_ext.name}")

    logger.verbose("BUILD", "[OK] Branding applied")
