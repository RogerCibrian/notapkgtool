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

"""MSI ProductVersion extraction for NAPT.

This module extracts the ProductVersion property from Windows Installer (MSI)
database files. It tries multiple backends in order of preference to maximize
cross-platform compatibility.

Backend Priority:

On Windows:

1. msilib (Python standard library, Python 3.11+)
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

        from pathlib import Path
        from notapkgtool.versioning.msi import version_from_msi_product_version
        discovered = version_from_msi_product_version("chrome.msi")
        print(f"{discovered.version} from {discovered.source}")
        # 141.0.7390.123 from msi

    Error handling:

        try:
            discovered = version_from_msi_product_version("missing.msi")
        except FileNotFoundError:
            print("MSI file not found")
        except RuntimeError as e:
            print(f"Extraction failed: {e}")

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

try:
    import msilib  # type: ignore  # Windows-only standard library module
except ImportError:
    msilib = None  # type: ignore

from .keys import DiscoveredVersion  # reuse the shared DTO


def version_from_msi_product_version(
    file_path: str | Path, verbose: bool = False, debug: bool = False
) -> DiscoveredVersion:
    """Extract ProductVersion from an MSI file.

    Uses cross-platform backends to read the MSI Property table. On Windows,
    tries msilib (Python 3.11+), _msi extension, then PowerShell COM API as
    universal fallback. On Linux/macOS, requires msitools package.

    Args:
        file_path: Path to the MSI file.
        verbose: If True, print verbose logging messages.
            Default is False.
        debug: If True, print debug logging messages.
            Default is False.

    Returns:
        Discovered version with source information.

    Raises:
        FileNotFoundError: If the MSI file doesn't exist.
        RuntimeError: If version extraction fails.
        NotImplementedError: If no extraction backend is available on this system.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"MSI not found: {p}")

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
                raise RuntimeError("ProductVersion not found in MSI Property table.")
            version = rec.GetString(1)
            db.Close()
            if not version:
                raise RuntimeError("Empty ProductVersion in MSI Property table.")
            logger.verbose("VERSION", f"Success! Extracted: {version} (via msilib)")
            return DiscoveredVersion(version=version, source="msi")
        except Exception as err:
            logger.debug("VERSION", "msilib failed, trying next backend...")
            raise RuntimeError(
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
                    raise RuntimeError(
                        "ProductVersion not found in MSI Property table."
                    )
                version = rec.GetString(1)
                if not version:
                    raise RuntimeError("Empty ProductVersion in MSI Property table.")
                view.Close()
                db.Close()
                logger.verbose("VERSION", f"Success! Extracted: {version} (via _msi)")
                return DiscoveredVersion(version=version, source="msi")
            except Exception as err:
                logger.debug("VERSION", "_msi failed, trying next backend...")
                raise RuntimeError(
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
            raise RuntimeError(f"PowerShell MSI query failed: {err}") from err
        except subprocess.TimeoutExpired:
            logger.debug("VERSION", "PowerShell COM timed out, trying next backend...")
            raise RuntimeError("PowerShell MSI query timed out") from None

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
                raise RuntimeError("ProductVersion not found in MSI Property output.")
            logger.verbose("VERSION", f"Success! Extracted: {version_str} (via msiinfo)")
            return DiscoveredVersion(version=version_str, source="msi")
        except subprocess.CalledProcessError as err:
            logger.debug("VERSION", "msiinfo failed")
            raise RuntimeError(f"msiinfo failed: {err}") from err

    logger.debug("VERSION", "No MSI extraction backend available on this system")
    raise NotImplementedError(
        "MSI version extraction is not available on this host. "
        "On Windows, ensure PowerShell is available. "
        "On Linux/macOS, install 'msitools'."
    )
