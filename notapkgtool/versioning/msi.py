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
It tries multiple backends in order of preference to maximize cross-platform
compatibility.

Backend Priority:

On Windows:

1. msilib (Python standard library, Python 3.10 and earlier only - removed in 3.13)
2. _msi (CPython extension module, Windows-specific)
3. PowerShell COM (Windows Installer COM API, always available)

On Linux/macOS:

1. msiinfo (from msitools package, must be installed separately)

    The PowerShell fallback makes this truly universal on Windows systems,
    even when Python MSI libraries aren't available.

Installation Requirements:

Windows:

- No additional packages required (PowerShell fallback always works)
- Optional: Ensure msilib is available for better performance

Linux/macOS:

- Install msitools package:
    - Debian/Ubuntu: `sudo apt-get install msitools`
    - RHEL/Fedora: `sudo dnf install msitools`
    - macOS: `brew install msitools`

Example:
    Extract version from MSI:
        ```python
        from pathlib import Path
        from notapkgtool.versioning.msi import version_from_msi_product_version
        discovered = version_from_msi_product_version("chrome.msi")
        print(f"{discovered.version} from {discovered.source}")
        # 141.0.7390.123 from msi
        ```

    Error handling:
        ```python
        try:
            discovered = version_from_msi_product_version("missing.msi")
        except PackagingError as e:
            print(f"Extraction failed: {e}")
        ```

Note:
    This is pure file introspection; no network calls are made. All backends
    query the MSI Property table for ProductVersion. The PowerShell approach
    uses COM (WindowsInstaller.Installer). Errors are chained for debugging
    (check 'from err' clause).

"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Literal

try:
    import msilib  # type: ignore  # Windows-only standard library module
except ImportError:
    msilib = None  # type: ignore

from dataclasses import dataclass

from notapkgtool.exceptions import ConfigError, PackagingError

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
    """MSI Property table metadata.

    Attributes:
        product_name: ProductName from MSI (display name).
        product_version: ProductVersion from MSI.

    """

    product_name: str
    product_version: str


def version_from_msi_product_version(
    file_path: str | Path,
) -> DiscoveredVersion:
    """Extract ProductVersion from an MSI file.

    Uses cross-platform backends to read the MSI Property table. On Windows,
    tries msilib (Python 3.10 and earlier - removed in 3.13), _msi extension,
    then PowerShell COM API as universal fallback. On Linux/macOS, requires
    msitools package.

    Args:
        file_path: Path to the MSI file.

    Returns:
        Discovered version with source information.

    Raises:
        PackagingError: If the MSI file doesn't exist or version extraction fails.
        NotImplementedError: If no extraction backend is available on this system.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise PackagingError(f"MSI not found: {p}")

    logger.verbose("VERSION", "Strategy: msi")
    logger.verbose("VERSION", f"Extracting version from: {p.name}")

    # Try msilib first (standard library on Windows)
    if sys.platform.startswith("win") and msilib is not None:
        logger.debug("VERSION", "Trying backend: msilib...")
        try:
            db = msilib.OpenDatabase(str(p), msilib.MSIDBOPEN_READONLY)
            view = db.OpenView(
                "SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'"
            )
            view.Execute(None)
            rec = view.Fetch()
            if rec is None:
                db.Close()
                raise PackagingError("ProductVersion not found in MSI Property table.")
            version = rec.GetString(1)
            db.Close()
            if not version:
                raise PackagingError("Empty ProductVersion in MSI Property table.")
            logger.verbose("VERSION", f"Success! Extracted: {version} (via msilib)")
            return DiscoveredVersion(version=version, source="msi")
        except Exception as err:
            logger.debug("VERSION", "msilib failed, trying next backend...")
            raise PackagingError(
                f"failed to read MSI ProductVersion via msilib: {err}"
            ) from err

    # Try _msi module (alternative Windows approach)
    if sys.platform.startswith("win"):
        logger.debug("VERSION", "Trying backend: _msi...")
        try:
            import _msi  # type: ignore
        except ImportError:
            # _msi not available, fall through to msiinfo
            logger.debug("VERSION", "_msi not available, trying next backend...")
            pass
        else:
            try:
                db = _msi.OpenDatabase(str(p), 0)  # 0: read-only
                view = db.OpenView(
                    "SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'"
                )
                view.Execute(None)
                rec = view.Fetch()
                if rec is None:
                    raise PackagingError(
                        "ProductVersion not found in MSI Property table."
                    )
                version = rec.GetString(1)
                if not version:
                    raise PackagingError("Empty ProductVersion in MSI Property table.")
                view.Close()
                db.Close()
                logger.verbose("VERSION", f"Success! Extracted: {version} (via _msi)")
                return DiscoveredVersion(version=version, source="msi")
            except Exception as err:
                logger.debug("VERSION", "_msi failed, trying next backend...")
                raise PackagingError(
                    f"failed to read MSI ProductVersion via _msi: {err}"
                ) from err

    # Try PowerShell with Windows Installer COM on Windows
    if sys.platform.startswith("win"):
        logger.debug("VERSION", "Trying backend: PowerShell COM...")
        try:
            ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{p}', 0)
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
            logger.debug("VERSION", "PowerShell COM failed, trying next backend...")
            raise PackagingError(f"PowerShell MSI query failed: {err}") from err
        except subprocess.TimeoutExpired:
            logger.debug("VERSION", "PowerShell COM timed out, trying next backend...")
            raise PackagingError("PowerShell MSI query timed out") from None

    # Try msiinfo on Linux/macOS
    msiinfo = shutil.which("msiinfo")
    if msiinfo:
        logger.debug("VERSION", "Trying backend: msiinfo (msitools)...")
        try:
            # msiinfo export <package> Property -> stdout (tab-separated)
            result = subprocess.run(
                [msiinfo, "export", str(p), "Property"],
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
            logger.debug("VERSION", "msiinfo failed")
            raise PackagingError(f"msiinfo failed: {err}") from err

    logger.debug("VERSION", "No MSI extraction backend available on this system")
    raise NotImplementedError(
        "MSI version extraction is not available on this host. "
        "On Windows, ensure PowerShell is available. "
        "On Linux/macOS, install 'msitools'."
    )


def extract_msi_metadata(file_path: str | Path) -> MSIMetadata:
    """Extract ProductName and ProductVersion from MSI file.

    Uses cross-platform backends to read the MSI Property table. On Windows,
    tries msilib (Python 3.10 and earlier - removed in 3.13), _msi extension,
    then PowerShell COM API as universal fallback. On Linux/macOS, requires
    msitools package.

    This function extracts multiple properties in one pass for efficiency.

    Args:
        file_path: Path to the MSI file.

    Returns:
        MSIMetadata with product information.

    Raises:
        PackagingError: If the MSI file doesn't exist or metadata extraction
            fails.
        NotImplementedError: If no extraction backend is available on this
            system.

    Example:
        Extract MSI metadata:
            ```python
            from pathlib import Path
            from notapkgtool.versioning.msi import extract_msi_metadata

            metadata = extract_msi_metadata(Path("chrome.msi"))
            print(f"{metadata.product_name} {metadata.product_version}")
            # Google Chrome 131.0.6778.86
            ```

    Note:
        ProductName may be empty string if not found in MSI. This is handled
        gracefully - build phase will fallback to recipe AppName if ProductName
        is empty.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise PackagingError(f"MSI not found: {p}")

    logger.verbose("MSI", f"Extracting metadata from: {p.name}")

    # Try msilib first (standard library on Windows)
    if sys.platform.startswith("win") and msilib is not None:
        logger.debug("MSI", "Trying backend: msilib...")
        try:
            db = msilib.OpenDatabase(str(p), msilib.MSIDBOPEN_READONLY)
            # Query for ProductName and ProductVersion
            view = db.OpenView(
                "SELECT `Property`,`Value` FROM `Property` "
                "WHERE `Property` IN ('ProductName','ProductVersion')"
            )
            view.Execute(None)

            metadata = {"ProductName": "", "ProductVersion": ""}
            while True:
                rec = view.Fetch()
                if rec is None:
                    break
                prop_name = rec.GetString(1)
                prop_value = rec.GetString(2)
                if prop_name in metadata:
                    metadata[prop_name] = prop_value

            view.Close()
            db.Close()

            if not metadata["ProductVersion"]:
                raise PackagingError("ProductVersion not found in MSI Property table.")

            logger.verbose(
                "MSI",
                f"Success! Extracted: {metadata['ProductName']} "
                f"{metadata['ProductVersion']} (via msilib)",
            )
            return MSIMetadata(
                product_name=metadata["ProductName"] or "",
                product_version=metadata["ProductVersion"],
            )
        except Exception as err:
            logger.debug("MSI", f"msilib failed: {err}, trying next backend...")

    # Try _msi module (alternative Windows approach)
    if sys.platform.startswith("win"):
        logger.debug("MSI", "Trying backend: _msi...")
        try:
            import _msi  # type: ignore
        except ImportError:
            logger.debug("MSI", "_msi not available, trying next backend...")
        else:
            try:
                db = _msi.OpenDatabase(str(p), 0)  # 0: read-only
                view = db.OpenView(
                    "SELECT `Property`,`Value` FROM `Property` "
                    "WHERE `Property` IN ('ProductName','ProductVersion')"
                )
                view.Execute(None)

                metadata = {
                    "ProductName": "",
                    "ProductVersion": "",
                }
                while True:
                    rec = view.Fetch()
                    if rec is None:
                        break
                    prop_name = rec.GetString(1)
                    prop_value = rec.GetString(2)
                    if prop_name in metadata:
                        metadata[prop_name] = prop_value

                view.Close()
                db.Close()

                if not metadata["ProductVersion"]:
                    raise PackagingError(
                        "ProductVersion not found in MSI Property table."
                    )

                logger.verbose(
                    "MSI",
                    f"Success! Extracted: {metadata['ProductName']} "
                    f"{metadata['ProductVersion']} (via _msi)",
                )
                return MSIMetadata(
                    product_name=metadata["ProductName"] or "",
                    product_version=metadata["ProductVersion"],
                )
            except Exception as err:
                logger.debug("MSI", f"_msi failed: {err}, trying next backend...")

    # Try PowerShell with Windows Installer COM on Windows
    if sys.platform.startswith("win"):
        logger.debug("MSI", "Trying backend: PowerShell COM...")
        try:
            # Escape single quotes in path by doubling them (PowerShell escaping)
            escaped_path = str(p).replace("'", "''")
            # Use double quotes for SQL string (PowerShell), single quotes for string literals (MSI SQL)
            # No backticks needed - Property and Value aren't reserved words
            ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{escaped_path}', 0)
if ($null -eq $db) {{
    Write-Error "Failed to open database: '{escaped_path}'"
    exit 1
}}
$sqlQuery = "SELECT Property, Value FROM Property WHERE Property = 'ProductName' OR Property = 'ProductVersion'"
$view = $db.OpenView($sqlQuery)
if ($null -eq $view) {{
    Write-Error "OpenView returned null for SQL: $sqlQuery"
    exit 1
}}
$view.Execute()
$metadata = @{{}}
while ($record = $view.Fetch()) {{
    $prop = $record.StringData(1)
    $value = $record.StringData(2)
    if ($prop -in @('ProductName','ProductVersion')) {{
        $metadata[$prop] = $value
    }}
}}
$view.Close()
$db.Close()
if (-not $metadata['ProductVersion']) {{
    Write-Error "ProductVersion not found"
    exit 1
}}
@($metadata['ProductName'], $metadata['ProductVersion']) -join "`n"
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().split("\n")
            product_name = lines[0] if len(lines) > 0 else ""
            product_version = lines[1] if len(lines) > 1 else ""

            if not product_version:
                raise PackagingError("ProductVersion not found in MSI Property table.")

            logger.verbose(
                "MSI",
                f"Success! Extracted: {product_name} {product_version} "
                "(via PowerShell COM)",
            )
            return MSIMetadata(
                product_name=product_name or "",
                product_version=product_version,
            )
        except subprocess.CalledProcessError as err:
            # Capture stderr to see what PowerShell actually reported
            stderr_output = err.stderr if err.stderr else "No stderr captured"
            stdout_output = err.stdout if err.stdout else "No stdout captured"
            logger.debug(
                "MSI",
                f"PowerShell COM failed: {err}. stdout: {stdout_output}, stderr: {stderr_output}. Trying next backend...",
            )
        except subprocess.TimeoutExpired:
            logger.debug("MSI", "PowerShell COM timed out, trying next backend...")
        except Exception as err:
            logger.debug("MSI", f"PowerShell COM failed: {err}, trying next backend...")

    # Try msiinfo on Linux/macOS (or as last resort on Windows)
    msiinfo = shutil.which("msiinfo")
    if msiinfo:
        logger.debug("MSI", "Trying backend: msiinfo (msitools)...")
        try:
            # msiinfo export <package> Property -> stdout (tab-separated)
            result = subprocess.run(
                [msiinfo, "export", str(p), "Property"],
                check=True,
                capture_output=True,
                text=True,
            )
            metadata = {"ProductName": "", "ProductVersion": ""}
            for line in result.stdout.splitlines():
                parts = line.strip().split("\t", 1)  # "Property<TAB>Value"
                if len(parts) == 2:
                    prop_name = parts[0]
                    prop_value = parts[1]
                    if prop_name in metadata:
                        metadata[prop_name] = prop_value

            if not metadata["ProductVersion"]:
                raise PackagingError("ProductVersion not found in MSI Property output.")

            logger.verbose(
                "MSI",
                f"Success! Extracted: {metadata['ProductName']} "
                f"{metadata['ProductVersion']} (via msiinfo)",
            )
            return MSIMetadata(
                product_name=metadata["ProductName"] or "",
                product_version=metadata["ProductVersion"],
            )
        except Exception as err:
            logger.debug("MSI", f"msiinfo failed: {err}")

    # All backends failed
    logger.debug("MSI", "No MSI extraction backend available on this system")
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


def extract_msi_architecture(file_path: str | Path) -> Architecture:
    """Extract architecture from MSI Summary Information Template property.

    Uses cross-platform backends to read the MSI Summary Information stream.
    On Windows, uses PowerShell COM API. On Linux/macOS, requires msitools.

    Args:
        file_path: Path to the MSI file.

    Returns:
        Architecture value: "x86", "x64", or "arm64".

    Raises:
        PackagingError: If the MSI file doesn't exist or extraction fails.
        ConfigError: If the platform is not supported by Intune.
        NotImplementedError: If no extraction backend is available.

    Example:
        Extract architecture from MSI:
            ```python
            from notapkgtool.versioning.msi import extract_msi_architecture

            arch = extract_msi_architecture("chrome.msi")
            print(f"Architecture: {arch}")
            # Architecture: x64
            ```

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise PackagingError(f"MSI not found: {p}")

    logger.verbose("MSI", f"Extracting architecture from: {p.name}")

    template: str | None = None

    # Try PowerShell with Windows Installer COM on Windows
    # Summary Information Property ID 7 is Template
    if sys.platform.startswith("win"):
        logger.debug("MSI", "Trying backend: PowerShell COM (SummaryInformation)...")
        try:
            escaped_path = str(p).replace("'", "''")
            ps_script = f"""
$installer = New-Object -ComObject WindowsInstaller.Installer
$db = $installer.OpenDatabase('{escaped_path}', 0)
if ($null -eq $db) {{
    Write-Error "Failed to open database: '{escaped_path}'"
    exit 1
}}
$sumInfo = $db.SummaryInformation(0)
$template = $sumInfo.Property(7)
$db.Close()
$template
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            template = result.stdout.strip()
            logger.verbose(
                "MSI",
                f"Success! Extracted Template: '{template}' (via PowerShell COM)",
            )
        except subprocess.CalledProcessError as err:
            stderr_output = err.stderr if err.stderr else "No stderr"
            logger.debug(
                "MSI",
                f"PowerShell COM failed: {err}. stderr: {stderr_output}. "
                "Trying next backend...",
            )
        except subprocess.TimeoutExpired:
            logger.debug("MSI", "PowerShell COM timed out, trying next backend...")
        except Exception as err:
            logger.debug("MSI", f"PowerShell COM failed: {err}, trying next backend...")

    # Try msiinfo on Linux/macOS (or as fallback on Windows)
    if template is None:
        msiinfo = shutil.which("msiinfo")
        if msiinfo:
            logger.debug("MSI", "Trying backend: msiinfo suminfo...")
            try:
                # msiinfo suminfo <package> outputs summary information
                result = subprocess.run(
                    [msiinfo, "suminfo", str(p)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                # Parse output for Template line
                # Format: "Template: x64;1033"
                for line in result.stdout.splitlines():
                    if line.startswith("Template:"):
                        template = line.split(":", 1)[1].strip()
                        break

                if template is not None:
                    logger.verbose(
                        "MSI",
                        f"Success! Extracted Template: '{template}' (via msiinfo)",
                    )
            except subprocess.CalledProcessError as err:
                logger.debug("MSI", f"msiinfo suminfo failed: {err}")
            except Exception as err:
                logger.debug("MSI", f"msiinfo failed: {err}")

    if template is None:
        logger.debug("MSI", "No backend could extract Template property")
        raise NotImplementedError(
            "MSI architecture extraction is not available on this host. "
            "On Windows, ensure PowerShell is available. "
            "On Linux/macOS, install 'msitools'."
        )

    # Parse the template into architecture
    return architecture_from_template(template)
