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

"""MSI metadata extraction for NAPT.

This module extracts metadata from Windows Installer (MSI) database files,
including ProductVersion, ProductName, and architecture (from Template).

Backend Priority:

On Windows:

1. PowerShell COM (Windows Installer COM API, always available)

On Linux/macOS:

1. msiinfo (from msitools package, must be installed separately)

Installation Requirements:

Windows:

- No additional packages required (PowerShell is always available)

Linux/macOS:

- Install msitools package:
    - Debian/Ubuntu: `sudo apt-get install msitools`
    - RHEL/Fedora: `sudo dnf install msitools`
    - macOS: `brew install msitools`

Example:
    Extract version from MSI:
        ```python
        from pathlib import Path
        from napt.versioning.msi import version_from_msi_product_version
        discovered = version_from_msi_product_version("chrome.msi")
        print(f"{discovered.version} from {discovered.source}")
        # 141.0.7390.123 from msi
        ```

    Extract full metadata including architecture:
        ```python
        from napt.versioning.msi import extract_msi_metadata
        metadata = extract_msi_metadata("chrome.msi")
        print(f"{metadata.product_name} {metadata.product_version} ({metadata.architecture})")
        # Google Chrome 144.0.7559.110 (x64)
        ```

Note:
    This is pure file introspection; no network calls are made. The PowerShell
    COM backend reads both the Property table (ProductName, ProductVersion) and
    Summary Information stream (Template/architecture) in a single database open.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Literal

from napt.exceptions import ConfigError, PackagingError

from .keys import DiscoveredVersion  # reuse the shared DTO

# MSI Template platform mapping
# See: https://learn.microsoft.com/en-us/windows/win32/msi/template-summary
_TEMPLATE_TO_ARCH: dict[str, str] = {
    "intel": "x86",  # Official 32-bit
    "x64": "x64",  # Official 64-bit (AMD64/x86-64)
    "amd64": "x64",  # Unofficial alias (defensive)
    "arm64": "arm64",  # Official 64-bit ARM
    # Note: Empty string defaults to Intel (x86) per MS docs
}

# Unsupported platforms that raise ConfigError
_UNSUPPORTED_PLATFORMS: dict[str, str] = {
    "intel64": "Itanium (Intel64) is not supported by Intune",
    "arm": "Windows RT 32-bit ARM is not supported by Intune",
}

# Type alias for architecture values
Architecture = Literal["x86", "x64", "arm64"]


@dataclass(frozen=True)
class MSIMetadata:
    """Represents metadata extracted from an MSI file.

    Attributes:
        product_name: ProductName from MSI Property table (display name).
        product_version: ProductVersion from MSI Property table.
        architecture: Installer architecture from MSI Template Summary
            Information property. Always one of "x86", "x64", or "arm64".

    """

    product_name: str
    product_version: str
    architecture: Architecture


def version_from_msi_product_version(
    file_path: str | Path,
) -> DiscoveredVersion:
    """Extract ProductVersion from an MSI file.

    Uses cross-platform backends to read the MSI Property table.
    On Windows, uses the PowerShell COM API. On Linux/macOS, requires msitools.

    Args:
        file_path: Path to the MSI file.

    Returns:
        Discovered version with source information.

    Raises:
        PackagingError: If the MSI file doesn't exist or version extraction fails.
        NotImplementedError: If no extraction backend is available on this system.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise PackagingError(f"MSI not found: {p}")

    logger.verbose("VERSION", "Strategy: msi")
    logger.verbose("VERSION", f"Extracting version from: {p.name}")

    # Try PowerShell with Windows Installer COM on Windows
    if sys.platform.startswith("win"):
        logger.debug("VERSION", "Trying backend: PowerShell COM...")
        try:
            escaped_path = str(p).replace("'", "''")
            ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{escaped_path}', 0)
$view = $db.OpenView("SELECT Value FROM Property WHERE Property='ProductVersion'")
$view.Execute()
$record = $view.Fetch()
if ($record) {{
    $record.StringData(1)
}} else {{
    Write-Error "ProductVersion not found"
    exit 1
}}
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            version = result.stdout.strip()
            if version:
                logger.verbose(
                    "VERSION", f"Success! Extracted: {version} (via PowerShell COM)"
                )
                return DiscoveredVersion(version=version, source="msi")
        except subprocess.CalledProcessError as err:
            raise PackagingError(f"PowerShell MSI query failed: {err}") from err
        except subprocess.TimeoutExpired:
            raise PackagingError("PowerShell MSI query timed out") from None

    # Try msiinfo on Linux/macOS
    msiinfo_bin = shutil.which("msiinfo")
    if msiinfo_bin:
        logger.debug("VERSION", "Trying backend: msiinfo (msitools)...")
        try:
            result = subprocess.run(
                [msiinfo_bin, "export", str(p), "Property"],
                check=True,
                capture_output=True,
                text=True,
            )
            version_str: str | None = None
            for line in result.stdout.splitlines():
                parts = line.strip().split("\t", 1)  # "Property<TAB>Value"
                if len(parts) == 2 and parts[0] == "ProductVersion":
                    version_str = parts[1]
                    break
            if not version_str:
                raise PackagingError("ProductVersion not found in MSI Property output.")
            logger.verbose(
                "VERSION", f"Success! Extracted: {version_str} (via msiinfo)"
            )
            return DiscoveredVersion(version=version_str, source="msi")
        except subprocess.CalledProcessError as err:
            raise PackagingError(f"msiinfo failed: {err}") from err

    logger.debug("VERSION", "No MSI extraction backend available on this system")
    raise NotImplementedError(
        "MSI version extraction is not available on this host. "
        "On Windows, ensure PowerShell is available. "
        "On Linux/macOS, install 'msitools'."
    )


def extract_msi_metadata(file_path: str | Path) -> MSIMetadata:
    """Extract ProductName, ProductVersion, and architecture from MSI file.

    Reads the MSI Property table (ProductName, ProductVersion) and Summary
    Information stream (Template/architecture) in a single database open.
    On Windows, uses the PowerShell COM API. On Linux/macOS, requires msitools.

    Args:
        file_path: Path to the MSI file.

    Returns:
        MSI metadata including product name, version, and architecture.

    Raises:
        PackagingError: If the MSI file doesn't exist or metadata extraction
            fails.
        ConfigError: If the MSI platform is not supported by Intune.
        NotImplementedError: If no extraction backend is available on this
            system.

    Example:
        Extract MSI metadata:
            ```python
            from pathlib import Path
            from napt.versioning.msi import extract_msi_metadata

            metadata = extract_msi_metadata(Path("chrome.msi"))
            print(f"{metadata.product_name} {metadata.product_version} ({metadata.architecture})")
            # Google Chrome 131.0.6778.86 (x64)
            ```

    Note:
        ProductName may be empty string if not found in MSI. The build phase
        validates ProductName and raises ConfigError if empty — it is required
        for detection script generation.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise PackagingError(f"MSI not found: {p}")

    logger.verbose("MSI", f"Extracting metadata from: {p.name}")

    # PowerShell COM (Windows only)
    if sys.platform.startswith("win"):
        logger.debug("MSI", "Trying backend: PowerShell COM...")
        escaped_path = str(p).replace("'", "''")
        ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{escaped_path}', 0)
if ($null -eq $db) {{
    Write-Error "Failed to open database"
    exit 1
}}
$view = $db.OpenView("SELECT Property, Value FROM Property WHERE Property = 'ProductName' OR Property = 'ProductVersion'")
$view.Execute()
$props = @{{}}
while ($record = $view.Fetch()) {{
    $props[$record.StringData(1)] = $record.StringData(2)
}}
$view.Close()
if (-not $props['ProductVersion']) {{
    Write-Error "ProductVersion not found"
    exit 1
}}
$sumInfo = $db.SummaryInformation(0)
$template = $sumInfo.Property(7)
$db.Close()
if (-not $template) {{
    Write-Error "Template (Summary Information Property 7) not found"
    exit 1
}}
@($props['ProductName'], $props['ProductVersion'], $template) -join "`n"
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.splitlines()
            product_name = lines[0] if len(lines) > 0 else ""
            product_version = lines[1] if len(lines) > 1 else ""
            template = lines[2] if len(lines) > 2 else ""

            if not product_version:
                raise PackagingError("ProductVersion not found in MSI Property table.")
            if not template:
                raise PackagingError(
                    "Template not found in MSI Summary Information stream."
                )

            architecture = architecture_from_template(template)
            logger.verbose(
                "MSI",
                f"[OK] Extracted: {product_name} {product_version} "
                f"({architecture}) (via PowerShell COM)",
            )
            return MSIMetadata(
                product_name=product_name,
                product_version=product_version,
                architecture=architecture,
            )
        except subprocess.CalledProcessError as err:
            stderr_output = err.stderr if err.stderr else "No stderr captured"
            raise PackagingError(
                f"PowerShell MSI query failed (exit {err.returncode}). "
                f"stderr: {stderr_output}"
            ) from err
        except subprocess.TimeoutExpired:
            raise PackagingError("PowerShell MSI query timed out") from None

    # msiinfo (Linux/macOS)
    msiinfo_bin = shutil.which("msiinfo")
    if msiinfo_bin:
        logger.debug("MSI", "Trying backend: msiinfo (msitools)...")
        try:
            prop_result = subprocess.run(
                [msiinfo_bin, "export", str(p), "Property"],
                check=True,
                capture_output=True,
                text=True,
            )
            props: dict[str, str] = {}
            for line in prop_result.stdout.splitlines():
                parts = line.strip().split("\t", 1)
                if len(parts) == 2:
                    props[parts[0]] = parts[1]

            product_version = props.get("ProductVersion", "")
            if not product_version:
                raise PackagingError("ProductVersion not found in MSI Property output.")

            suminfo_result = subprocess.run(
                [msiinfo_bin, "suminfo", str(p)],
                check=True,
                capture_output=True,
                text=True,
            )
            template: str | None = None
            for line in suminfo_result.stdout.splitlines():
                if line.startswith("Template:"):
                    template = line.split(":", 1)[1].strip()
                    break

            if template is None:
                raise PackagingError(
                    "Template not found in MSI Summary Information stream."
                )

            architecture = architecture_from_template(template)
            product_name = props.get("ProductName", "")
            logger.verbose(
                "MSI",
                f"[OK] Extracted: {product_name} {product_version} "
                f"({architecture}) (via msiinfo)",
            )
            return MSIMetadata(
                product_name=product_name,
                product_version=product_version,
                architecture=architecture,
            )
        except subprocess.CalledProcessError as err:
            raise PackagingError(f"msiinfo failed: {err}") from err

    raise NotImplementedError(
        "MSI metadata extraction is not available on this host. "
        "On Windows, ensure PowerShell is available. "
        "On Linux/macOS, install 'msitools'."
    )


def architecture_from_template(template: str) -> Architecture:
    """Parse MSI Template property into NAPT architecture value.

    The Template property format is platform;language_id (semicolon, then
    optional language codes). Examples: "x64;1033", "Intel;1033,1041",
    ";1033" (empty platform defaults to Intel).

    Args:
        template: Raw Template property string from MSI Summary Information.

    Returns:
        Architecture value: "x86", "x64", or "arm64".

    Raises:
        ConfigError: If the platform is not supported by Intune (Itanium, ARM32).

    Example:
        Parse template strings:
            ```python
            arch = architecture_from_template("x64;1033")
            # Returns: "x64"

            arch = architecture_from_template("Intel;1033")
            # Returns: "x86"

            arch = architecture_from_template(";1033")
            # Returns: "x86" (empty defaults to Intel)
            ```

    """
    # Split on semicolon and take only the first token (platform)
    # Discard remaining tokens (language codes like 1033)
    platform = template.split(";")[0].strip().lower()

    # Empty platform defaults to Intel (x86) per Microsoft docs
    if not platform:
        return "x86"

    # Check for unsupported platforms first
    if platform in _UNSUPPORTED_PLATFORMS:
        raise ConfigError(
            f"MSI platform '{platform}' is not supported. "
            f"{_UNSUPPORTED_PLATFORMS[platform]}."
        )

    # Map to NAPT architecture
    arch = _TEMPLATE_TO_ARCH.get(platform)
    if arch is None:
        raise ConfigError(
            f"Unknown MSI platform '{platform}' in Template property. "
            f"Expected one of: Intel, x64, AMD64, Arm64."
        )

    return arch  # type: ignore[return-value]
