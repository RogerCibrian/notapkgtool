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

"""Install and uninstall commands for the generated deployment script.

MSI and MSIX installers carry enough metadata to generate both commands;
the recipe's own ``psadt.install`` and ``psadt.uninstall`` are used only
when the matching override flag is set. EXE recipes always supply their
own, so there is nothing to generate for them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from napt.build.installer import InstallerInfo
from napt.exceptions import ConfigError, PackagingError
from napt.logging import get_global_logger
from napt.powershell import ps_single_quote
from napt.versioning.msi import MSIMetadata
from napt.versioning.msix import MSIXMetadata


def _apply_overrides(
    config: dict[str, Any],
    *,
    label: str,
    flag: str,
    source: str,
    auto_install: str,
    auto_uninstall: Callable[[], str],
) -> None:
    """Injects the generated commands, honoring the recipe's override flag.

    Without the flag, both commands are generated and a recipe command
    draws a warning. With it, a recipe command is kept and only a missing
    one is generated.

    Args:
        config: Recipe configuration, mutated in place.
        label: Installer type for messages ("MSI" or "MSIX").
        flag: The ``psadt`` override flag for this installer type.
        source: Where the generated commands come from, for the warning.
        auto_install: The generated install command.
        auto_uninstall: Produces the generated uninstall command on demand,
            so its checks run only when the command is used.

    Raises:
        ConfigError: If the flag is set but neither recipe command is.
    """
    logger = get_global_logger()
    psadt = config["psadt"]
    recipe_install = psadt.get("install")
    recipe_uninstall = psadt.get("uninstall")

    if psadt.get(flag, False):
        if not recipe_install and not recipe_uninstall:
            raise ConfigError(
                f"psadt.{flag} is true but neither psadt.install nor "
                f"psadt.uninstall is set. Set psadt.install and/or "
                f"psadt.uninstall when using {flag}."
            )
        if recipe_install:
            logger.verbose("BUILD", f"Using recipe psadt.install ({flag})")
        else:
            psadt["install"] = auto_install
            logger.info("BUILD", f"Auto-generated {label} install: {auto_install}")
        if recipe_uninstall:
            logger.verbose("BUILD", f"Using recipe psadt.uninstall ({flag})")
        else:
            psadt["uninstall"] = auto_uninstall()
            logger.info(
                "BUILD", f"Auto-generated {label} uninstall: {psadt['uninstall']}"
            )
        return

    for key, value in (("install", recipe_install), ("uninstall", recipe_uninstall)):
        if value:
            logger.warning(
                "BUILD",
                f"psadt.{key} is set but will be ignored for {label} installers. "
                f"{source} Set {flag}: true to use psadt.{key} instead.",
            )

    psadt["install"] = auto_install
    psadt["uninstall"] = auto_uninstall()
    logger.info("BUILD", f"Auto-generated {label} install: {auto_install}")
    logger.info("BUILD", f"Auto-generated {label} uninstall: {psadt['uninstall']}")


def _apply_msi_commands(
    config: dict[str, Any], msi_metadata: MSIMetadata, installer_file: Path
) -> None:
    """Generates MSI install/uninstall commands or applies the overrides.

    Install runs ``Start-ADTMsiProcess -Action Install`` on the exact
    installer filename; PSADT's configuration supplies the silent-install
    arguments and verbose logging, and ``ALLUSERS=1`` is appended under
    ``intune.run_as_account: system`` to force a per-machine install.
    Uninstall runs ``Uninstall-ADTApplication`` matching the MSI ProductName
    exactly, restricted to MSI applications; name matching keeps working
    when a vendor changes the ProductCode between versions.

    Args:
        config: Recipe configuration, mutated in place.
        msi_metadata: The installer's metadata.
        installer_file: The MSI installer file.

    Raises:
        ConfigError: If ``override_msi_commands`` is true but neither
            ``psadt.install`` nor ``psadt.uninstall`` is provided.
        PackagingError: If the MSI has no ProductName when the uninstall
            command must be generated. A recipe that overrides uninstall
            builds against such an MSI.
    """
    auto_install = (
        "Start-ADTMsiProcess -Action Install"
        f" -FilePath {ps_single_quote(installer_file.name)}"
    )
    if config["intune"]["run_as_account"] == "system":
        auto_install += ' -AdditionalArgumentList "ALLUSERS=1"'

    def auto_uninstall() -> str:
        if not msi_metadata.product_name:
            raise PackagingError(
                "MSI ProductName property not found. Cannot auto-generate "
                "the uninstall command. Set override_msi_commands: true and "
                "provide psadt.uninstall, or ensure the MSI file contains "
                "ProductName."
            )
        quoted_name = ps_single_quote(msi_metadata.product_name)
        return (
            f"Uninstall-ADTApplication -Name {quoted_name}"
            " -NameMatch 'Exact' -ApplicationType 'MSI'"
        )

    _apply_overrides(
        config,
        label="MSI",
        flag="override_msi_commands",
        source="The commands are generated from the MSI.",
        auto_install=auto_install,
        auto_uninstall=auto_uninstall,
    )


def _apply_msix_commands(
    config: dict[str, Any], msix_metadata: MSIXMetadata, installer_file: Path
) -> None:
    """Generates MSIX install/uninstall commands or applies the overrides.

    The commands depend on ``intune.run_as_account``: ``system`` (the
    default) provisions the package for all users with
    ``Add-AppxProvisionedPackage`` and removes it with
    ``Remove-AppxProvisionedPackage``; ``user`` installs per user with
    ``Add-AppxPackage`` and removes with ``Remove-AppxPackage``.

    Args:
        config: Recipe configuration, mutated in place.
        msix_metadata: The installer's metadata.
        installer_file: The MSIX installer file.

    Raises:
        ConfigError: If ``override_msix_commands`` is true but neither
            ``psadt.install`` nor ``psadt.uninstall`` is provided.
    """
    # The filename and identity come from the vendor, so both are emitted as
    # single-quoted literals; Join-Path keeps the filename out of an
    # expandable string.
    package_path = (
        f"(Join-Path $adtSession.DirFiles {ps_single_quote(installer_file.name)})"
    )
    identity = ps_single_quote(msix_metadata.identity_name)

    if config["intune"]["run_as_account"] == "user":
        auto_install = f"Add-AppxPackage -Path {package_path}"
        auto_uninstall = f"Get-AppxPackage -Name {identity} | Remove-AppxPackage"
    else:
        auto_install = (
            f"Add-AppxProvisionedPackage -Online"
            f" -PackagePath {package_path}"
            f" -SkipLicense"
        )
        auto_uninstall = (
            f"Get-AppxProvisionedPackage -Online"
            f" | Where-Object {{ $_.DisplayName -eq {identity} }}"
            f" | Remove-AppxProvisionedPackage -Online"
        )

    _apply_overrides(
        config,
        label="MSIX",
        flag="override_msix_commands",
        source="The commands are generated from the MSIX manifest.",
        auto_install=auto_install,
        auto_uninstall=lambda: auto_uninstall,
    )


def apply_install_commands(config: dict[str, Any], installer: InstallerInfo) -> None:
    """Sets the install and uninstall commands the deployment script runs.

    Args:
        config: Recipe configuration, mutated in place for MSI and MSIX.
        installer: The inspected installer.

    Raises:
        ConfigError: If an override flag is set without a command to use.
        PackagingError: If an MSI has no ProductName to uninstall by.
    """
    if installer.kind == ".msi":
        assert installer.msi is not None  # set by inspect_installer
        _apply_msi_commands(config, installer.msi, installer.path)
    elif installer.kind == ".msix":
        assert installer.msix is not None  # set by inspect_installer
        _apply_msix_commands(config, installer.msix, installer.path)
