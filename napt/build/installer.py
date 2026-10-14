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

"""The installer a build is made from: finding it and reading it once.

`napt build` resolves its installer in three steps that all live here: the
release deployment state records, the file in that version's download
folder whose hash matches, and what that file says about itself. The
result is one [InstallerInfo][napt.build.installer.InstallerInfo] that the
rest of the build reads instead of opening the installer again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from napt.build.registry_scripts import ArchitectureMode
from napt.download.download import sha256_file
from napt.exceptions import ConfigError, PackagingError, StateError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component
from napt.powershell import strip_control_characters
from napt.state.deployment import working_release
from napt.versioning.msi import MSIMetadata, extract_msi_metadata
from napt.versioning.msix import MSIXMetadata, extract_msix_metadata

_INSTALLER_SUFFIXES = (".msi", ".msix", ".exe")


@dataclass(frozen=True)
class InstallerInfo:
    """What the build knows about its installer after reading it once.

    Attributes:
        path: The installer file under the downloads directory.
        sha256: Its hex digest, the one recorded at discovery.
        version: The version being built, the name of the download folder.
        app_name: The display name the detection scripts look for: the MSI
            ProductName or MSIX DisplayName, or the recipe's
            ``intune.detection.display_name``.
        architecture: The registry view the scripts check, read from the
            installer for MSI and MSIX and from
            ``intune.detection.architecture`` for EXE.
        msi: The MSI metadata, for an MSI installer.
        msix: The MSIX metadata, for an MSIX installer.
    """

    path: Path
    sha256: str
    version: str
    app_name: str
    architecture: ArchitectureMode
    msi: MSIMetadata | None = None
    msix: MSIXMetadata | None = None

    @property
    def kind(self) -> str:
        """The installer type as its lowercase suffix: ".msi", ".msix", or ".exe"."""
        return self.path.suffix.lower()


def release_to_build(
    config: dict[str, Any], state_dir: Path | None = None
) -> dict[str, Any] | None:
    """Reads the release to build from the app's deployment state.

    That is the pending release (awaiting publication), or the published
    release when nothing is pending, which is the case when rebuilding the
    current version. Deployment state is committed alongside recipes, so
    this works on machines that never ran discover, such as a CI publish
    job restoring downloads from a cache.

    Args:
        config: Recipe configuration.
        state_dir: State root, or None for ``directories.state``.

    Returns:
        The release entry (``version``, ``sha256``, ``url``), or None when
            no release is recorded.

    Raises:
        StateError: If the deployment state file exists but is corrupted
            or has an unsupported schema version.
    """
    if state_dir is None:
        state_dir = Path(config["directories"]["state"])
    return working_release(state_dir, config["id"])


def find_installer_file(
    downloads_dir: Path, app_id: str, release: dict[str, Any] | None
) -> tuple[Path, str]:
    """Finds the installer to build and returns it with its SHA-256.

    Discover saves each download to ``downloads/<id>/<version>/``. With a
    recorded release, the installer is the file in that version's folder
    whose hash matches the recorded one, so a file that was swapped or
    corrupted since discovery is refused rather than packaged.

    Without a recorded release (a stateless discover and no deployment
    state), there is nothing to match against, and the single installer
    found in one of the app's version folders is used.

    Args:
        downloads_dir: Downloads directory to search.
        app_id: Recipe id.
        release: The release to build (``version`` and ``sha256``), from
            [release_to_build][napt.build.installer.release_to_build], or
            None when no release is recorded.

    Returns:
        A tuple (installer_path, sha256), where
            installer_path is the installer file,
            sha256 is its hex digest.

    Raises:
        StateError: If the recorded version is not a plain folder name.
        PackagingError: If no file matches the recorded release, or, with
            no recorded release, if there is not exactly one installer.
    """
    logger = get_global_logger()
    app_dir = downloads_dir / app_id

    if release is not None:
        # State files are hand-editable and reviewed through pull requests, so
        # the recorded version is not trusted to stay inside the app's folder.
        if not is_safe_path_component(release["version"]):
            raise StateError(
                f"Deployment state for {app_id} records version "
                f"{release['version']!a}, which cannot be used as a folder name. "
                "Run 'napt discover' to record the release again."
            )
        version_dir = app_dir / release["version"]
        candidates = (
            [
                p
                for p in version_dir.iterdir()
                if p.is_file() and p.suffix.lower() in _INSTALLER_SUFFIXES
            ]
            if version_dir.is_dir()
            else []
        )
        for candidate in candidates:
            digest = sha256_file(candidate)
            if digest == release["sha256"]:
                logger.verbose("BUILD", f"Found installer: {candidate}")
                return candidate, digest
        raise PackagingError(
            f"No file in {version_dir} matches the recorded release of {app_id} "
            f"(version {release['version']}, sha256 {release['sha256']}). "
            f"Run 'napt discover' to download it."
        )

    # Only folders named like a version count. That skips ".incoming", where
    # an interrupted discover can leave a finished download behind.
    installers = sorted(
        p
        for p in app_dir.glob("*/*")
        if p.is_file()
        and p.suffix.lower() in _INSTALLER_SUFFIXES
        and is_safe_path_component(p.parent.name)
    )
    if len(installers) == 1:
        logger.verbose("BUILD", f"Found installer: {installers[0]}")
        return installers[0], sha256_file(installers[0])
    if not installers:
        raise PackagingError(
            f"No installer found for {app_id} under {app_dir}. "
            f"Run 'napt discover' first."
        )
    listing = ", ".join(str(p.relative_to(app_dir)) for p in installers)
    raise PackagingError(
        f"No release is recorded for {app_id}, and {app_dir} holds more than one "
        f"installer ({listing}). Run 'napt discover' without --stateless so "
        f"the release to build is recorded."
    )


def _check_version(installer_file: Path, reported: str, version: str) -> None:
    """Refuses an installer whose own version differs from its folder's name.

    Args:
        installer_file: The installer.
        reported: The version the installer's metadata carries.
        version: The download folder's name.

    Raises:
        PackagingError: If the two differ.
    """
    get_global_logger().verbose("BUILD", f"Extracted version: {reported}")
    if reported != version:
        raise PackagingError(
            f"{installer_file.name} reports version {reported} but is filed "
            f"under {installer_file.parent}. Run 'napt discover' to file it "
            "under its own version, or rename the folder to match."
        )


def _warn_ignored_fields(kind: str, detection: dict[str, Any]) -> None:
    """Warns once about recipe fields the installer type makes no use of.

    Args:
        kind: The installer suffix.
        detection: The recipe's ``intune.detection`` section.
    """
    logger = get_global_logger()
    override_display_name = detection.get("override_msi_display_name", False)

    if kind == ".msi" and detection.get("display_name") and not override_display_name:
        logger.warning(
            "BUILD",
            "intune.detection.display_name is set but will be ignored for "
            "MSI installers. MSI ProductName is used as the authoritative "
            "source for registry DisplayName. Set "
            "override_msi_display_name: true to use display_name instead.",
        )
    if kind == ".msi" and detection.get("architecture"):
        logger.warning(
            "BUILD",
            "intune.detection.architecture is set but will be ignored for MSI "
            "installers. MSI Template is used as the authoritative source for "
            "architecture.",
        )
    if kind == ".msix" and detection.get("display_name"):
        logger.warning(
            "BUILD",
            "intune.detection.display_name is set but will be ignored for "
            "MSIX installers. MSIX DisplayName is used as the authoritative "
            "source for detection.",
        )
    if kind == ".msix" and detection.get("architecture"):
        logger.warning(
            "BUILD",
            "intune.detection.architecture is set but will be ignored for "
            "MSIX installers. MSIX ProcessorArchitecture is used as the "
            "authoritative source for architecture.",
        )
    if kind != ".msi" and override_display_name:
        logger.warning(
            "BUILD",
            "intune.detection.override_msi_display_name is set but will "
            "be ignored for non-MSI installers. This flag only applies to "
            "MSI installers.",
        )


def _resolve_app_info(
    kind: str,
    detection: dict[str, Any],
    version: str,
    msi: MSIMetadata | None,
    msix: MSIXMetadata | None,
) -> tuple[str, ArchitectureMode]:
    """Resolves the display name and architecture the scripts are built for.

    Installer metadata is authoritative for MSI and MSIX; an EXE recipe
    supplies both through ``intune.detection``.

    Args:
        kind: The installer suffix.
        detection: The recipe's ``intune.detection`` section.
        version: The version being built, for ``{{discovered_version}}``.
        msi: MSI metadata, for an MSI installer.
        msix: MSIX metadata, for an MSIX installer.

    Returns:
        A tuple (app_name, architecture), where
            app_name is the display name the scripts look for,
            architecture is one of "x86", "x64", "arm64", "any".

    Raises:
        PackagingError: If an MSI has no ProductName to detect by.
        ConfigError: If an EXE recipe lacks display_name or architecture,
            or override_msi_display_name is set without a display_name.
    """
    logger = get_global_logger()

    if kind == ".msi":
        assert msi is not None  # set by inspect_installer
        if detection.get("override_msi_display_name", False):
            if not detection.get("display_name"):
                raise ConfigError(
                    "intune.detection.override_msi_display_name is true "
                    "but display_name is not set. Set "
                    "intune.detection.display_name when using "
                    "override_msi_display_name."
                )
            app_name = detection["display_name"].replace(
                "{{discovered_version}}", version
            )
            logger.verbose("BUILD", f"Using display_name (override): {app_name}")
        else:
            if not msi.product_name:
                raise PackagingError(
                    "MSI ProductName property not found. Cannot generate "
                    "scripts. Ensure the MSI file is valid and contains "
                    "ProductName property."
                )
            app_name = msi.product_name
            logger.verbose("BUILD", f"Using MSI ProductName: {app_name}")
        logger.verbose("BUILD", f"MSI architecture: {msi.architecture}")
        return app_name, msi.architecture

    if kind == ".msix":
        assert msix is not None  # set by inspect_installer
        logger.verbose("BUILD", f"Using MSIX DisplayName: {msix.display_name}")
        logger.verbose("BUILD", f"MSIX architecture: {msix.architecture}")
        return msix.display_name, msix.architecture

    if not detection.get("display_name"):
        raise ConfigError(
            "intune.detection.display_name is required for EXE installers. "
            "Set intune.detection.display_name in the recipe."
        )
    if not detection.get("architecture"):
        raise ConfigError(
            "intune.detection.architecture is required for EXE installers. "
            "Set intune.detection.architecture in the recipe. "
            "Allowed values: x86, x64, arm64, any"
        )
    app_name = detection["display_name"].replace("{{discovered_version}}", version)
    architecture = cast(ArchitectureMode, detection["architecture"])
    logger.verbose("BUILD", f"Using intune.detection.display_name: {app_name}")
    logger.verbose("BUILD", f"Using intune.detection.architecture: {architecture}")
    return app_name, architecture


def _require_exe_scripts(config: dict[str, Any]) -> None:
    """Checks that an EXE recipe supplies its own install and uninstall scripts.

    MSI and MSIX installers carry enough metadata to auto-generate the
    commands; EXE installers do not, so the recipe must provide both.

    Args:
        config: Effective configuration for the recipe.

    Raises:
        ConfigError: If ``psadt.install`` or ``psadt.uninstall`` is missing
            or blank.
    """
    psadt_scripts = config["psadt"]
    missing = [
        key
        for key in ("install", "uninstall")
        if not str(psadt_scripts.get(key) or "").strip()
    ]
    if missing:
        raise ConfigError(
            f"psadt.{' and psadt.'.join(missing)} required for EXE "
            "installers: NAPT can only auto-generate install and "
            "uninstall commands for MSI and MSIX packages"
        )


def inspect_installer(
    installer_file: Path, sha256: str, config: dict[str, Any]
) -> InstallerInfo:
    """Reads the installer once and resolves what the build needs from it.

    The version is the name of the folder discover filed the installer in
    (``downloads/<id>/<version>/``). An MSI or MSIX reports its own version,
    architecture, and name, and discover names the folder after the
    version, so the two must agree: a file moved into the wrong folder by
    hand would otherwise be built and detected under a version it does not
    carry. An EXE carries no usable metadata, so its recipe must supply the
    display name, the architecture, and both install commands. Recipe
    fields the installer type makes no use of draw one warning each.

    Args:
        installer_file: The installer found by
            [find_installer_file][napt.build.installer.find_installer_file].
        sha256: Its hex digest.
        config: Recipe configuration.

    Returns:
        Everything later build steps read about the installer.

    Raises:
        PackagingError: If the installer's metadata cannot be read, its
            version differs from its folder's name, or an MSI has no
            ProductName.
        ConfigError: If an EXE recipe lacks ``intune.detection.display_name``,
            ``intune.detection.architecture``, or ``psadt.install`` and
            ``psadt.uninstall``, or ``override_msi_display_name`` is set
            without a ``display_name``.
    """
    logger = get_global_logger()
    version = installer_file.parent.name
    kind = installer_file.suffix.lower()
    detection = config["intune"]["detection"]

    msi: MSIMetadata | None = None
    msix: MSIXMetadata | None = None
    if kind == ".msi":
        logger.verbose("BUILD", f"Reading MSI metadata: {installer_file.name}")
        msi = extract_msi_metadata(installer_file)
        _check_version(installer_file, msi.product_version, version)
    elif kind == ".msix":
        logger.verbose("BUILD", f"Reading MSIX manifest: {installer_file.name}")
        msix = extract_msix_metadata(installer_file)
        _check_version(installer_file, msix.version, version)
    else:
        logger.verbose("BUILD", f"Using discovered version: {version}")

    _warn_ignored_fields(kind, detection)
    app_name, architecture = _resolve_app_info(kind, detection, version, msi, msix)
    if kind == ".exe":
        _require_exe_scripts(config)

    # The name is written into a comment line and the script filenames, where
    # a line break would end the comment or break the name.
    cleaned = strip_control_characters(app_name)
    if cleaned != app_name:
        logger.warning(
            "BUILD",
            f"App name {app_name!a} contains control characters; using "
            f"{cleaned!a} for scripts and filenames",
        )

    return InstallerInfo(
        path=installer_file,
        sha256=sha256,
        version=version,
        app_name=cleaned,
        architecture=architecture,
        msi=msi,
        msix=msix,
    )
