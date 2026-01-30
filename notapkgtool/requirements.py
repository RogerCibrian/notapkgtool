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

"""Requirements script generation for Intune Win32 apps.

This module generates PowerShell requirements scripts for Intune Win32 app
deployments. Requirements scripts determine if the Update entry should be
applicable to a device based on whether an older version is installed.

Requirements Logic:
    - Checks HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Checks HKCU:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Matches by DisplayName (using AppName from recipe or MSI ProductName)
    - If installed version < target version: outputs "Required" and exits 0
    - Otherwise: outputs nothing and exits 0

Installer Type Filtering:
    Scripts filter registry entries based on installer type to prevent false
    matches when both MSI and EXE versions of software exist:

    - MSI installers (strict): Only matches registry entries with
        WindowsInstaller=1. Prevents false matches with EXE versions.
    - Non-MSI installers (permissive): Matches ANY registry entry. Handles
        EXE installers that run embedded MSIs internally.

Logging:
    - Primary (System): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTRequirements.log
    - Primary (User): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTRequirementsUser.log
    - Fallback (System): C:\\ProgramData\\NAPT\\NAPTRequirements.log
    - Fallback (User): %LOCALAPPDATA%\\NAPT\\NAPTRequirementsUser.log
    - Log rotation: 2-file rotation (.log and .log.old), configurable max size
        (default: 3MB)
    - Format: CMTrace format for compatibility with Intune diagnostics

Example:
    Generate requirements script:
        ```python
        from pathlib import Path
        from notapkgtool.requirements import RequirementsConfig, generate_requirements_script

        config = RequirementsConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        script_path = generate_requirements_script(
            config=config,
            output_path=Path("builds/chrome/131.0.6778.86/Google-Chrome-131.0.6778.86-Requirements.ps1"),
        )
        ```

Note:
    Requirements scripts are saved as siblings to the packagefiles directory
    to prevent them from being included in the .intunewin package. They
    should be uploaded separately to Intune as a custom requirement rule
    with output type String, operator Equals, value "Required".

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import string
from typing import Literal

LogFormat = Literal["cmtrace"]
LogLevel = Literal["INFO", "WARNING", "ERROR", "DEBUG"]


# Type alias for architecture values
ArchitectureMode = Literal["x86", "x64", "arm64", "any"]


@dataclass(frozen=True)
class RequirementsConfig:
    """Configuration for requirements script generation.

    Attributes:
        app_name: Application name to search for in registry DisplayName.
        version: Target version string (requirement met if installed < this).
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        app_id: Application ID (used for fallback if app_name sanitization
            results in empty string).
        is_msi_installer: If True, only match MSI-based registry entries.
            If False, only match non-MSI entries. This prevents false matches
            when both MSI and EXE versions of software exist with the same
            DisplayName.
        expected_architecture: Architecture filter for registry view selection.
            - "x86": Check only 32-bit registry view
            - "x64": Check only 64-bit registry view
            - "arm64": Check only 64-bit registry view (ARM64 uses 64-bit registry)
            - "any": Check both 32-bit and 64-bit views (permissive)
        use_wildcard: If True, use PowerShell -like operator for DisplayName
            matching (supports * and ? wildcards). If False, use exact -eq match.

    """

    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    app_id: str = ""
    is_msi_installer: bool = False
    expected_architecture: ArchitectureMode = "any"
    use_wildcard: bool = False


# PowerShell requirements script template
# TODO: Move this template to a separate .ps1 file for syntax highlighting and easier editing
_REQUIREMENTS_SCRIPT_TEMPLATE = """# Requirements script for ${app_name} ${version}
# Generated by NAPT (Not a Package Tool)
# This script checks if an older version is installed (for Update entry applicability).
# Outputs "Required" if installed version < target version, nothing otherwise.
# Always exits with code 0 so Intune can evaluate STDOUT.
# Uses explicit registry views for deterministic architecture-aware detection.

param(
    [string]$$AppName = "${app_name}",
    [string]$$TargetVersion = "${version}",
    [bool]$$IsMSIInstaller = ${is_msi_installer},
    [string]$$ExpectedArchitecture = "${expected_architecture}"
)

# CMTrace log format function
function Write-CMTraceLog {
    param(
        [string]$$Message,
        [string]$$Component = $$script:ComponentName,
        [string]$$Type = "INFO"  # "INFO", "WARNING", "ERROR", "DEBUG"
    )
    
    $$LogFile = $$script:LogFilePath
    
    if (-not $$LogFile) {
        return
    }
    
    # Convert string log level to CMTrace numeric type
    # 1=Info, 2=Warning, 3=Error, 4=Debug
    $$TypeNumber = switch ($$Type.ToUpper()) {
        "INFO" { 1 }
        "WARNING" { 2 }
        "ERROR" { 3 }
        "DEBUG" { 4 }
        default { 1 }  # Default to INFO if unknown
    }
    
    # Format time: HH:mm:ss.fff-offset (offset in minutes, e.g., -480 for -08:00)
    $$Now = [DateTimeOffset](Get-Date)
    $$TimeFormatted = $$Now.ToString("HH:mm:ss.fff")
    $$OffsetMinutes = [int]$$Now.Offset.TotalMinutes
    $$TimeWithOffset = "$$TimeFormatted$$OffsetMinutes"
    
    # Format date: M-d-yyyy (single digit month/day when appropriate)
    $$DateFormatted = $$Now.ToString("M-d-yyyy")
    
    # Get context (user identity name) and script file path
    $$ContextName = if ($$script:CurrentIdentity) { $$script:CurrentIdentity.Name } else { "UNKNOWN" }
    $$ScriptFile = if ($$MyInvocation.ScriptName) { $$MyInvocation.ScriptName } else { "requirements.ps1" }
    
    $$Line = "<![LOG[$$Message]LOG]!><time=""$$TimeWithOffset"" date=""$$DateFormatted"" component=""$$Component"" context=""$$ContextName"" type=""$$TypeNumber"" thread=""$$PID"" file=""$$ScriptFile"">"
    
    try {
        Add-Content -Path $$LogFile -Value $$Line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {
        # Silently fail if we can't write to log
    }
}

# Determine log file location
function Initialize-LogFile {
    $$script:CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $$IsSystemContext = $$script:CurrentIdentity.Name -eq "NT AUTHORITY\\SYSTEM"
    
    if ($$IsSystemContext) {
        # System context - try Intune log folder first
        $$PrimaryLogDir = "C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs"
        $$PrimaryLogFile = Join-Path $$PrimaryLogDir "NAPTRequirements.log"
        $$FallbackLogDir = "C:\\ProgramData\\NAPT"
        $$FallbackLogFile = Join-Path $$FallbackLogDir "NAPTRequirements.log"
    } else {
        # User context
        $$PrimaryLogDir = "C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs"
        $$PrimaryLogFile = Join-Path $$PrimaryLogDir "NAPTRequirementsUser.log"
        $$FallbackLogDir = $$env:LOCALAPPDATA
        $$FallbackLogFile = Join-Path $$FallbackLogDir "NAPT\\NAPTRequirementsUser.log"
    }
    
    # Try primary location first
    try {
        # Ensure parent directory exists (fails with -ErrorAction Stop if no perms)
        $$PrimaryLogParent = Split-Path -Path $$PrimaryLogFile -Parent
        if (-not (Test-Path -Path $$PrimaryLogParent)) {
            New-Item -Path $$PrimaryLogParent -ItemType Directory -Force -ErrorAction Stop | Out-Null
        }
        
        # Handle log rotation if needed
        if (Test-Path -Path $$PrimaryLogFile) {
            $$LogSize = (Get-Item $$PrimaryLogFile).Length
            $$MaxSize = ${log_rotation_mb} * 1024 * 1024
            if ($$LogSize -ge $$MaxSize) {
                $$OldLogFile = "$$PrimaryLogFile.old"
                if (Test-Path $$OldLogFile) { Remove-Item $$OldLogFile -Force -ErrorAction Stop }
                Move-Item -Path $$PrimaryLogFile -Destination $$OldLogFile -Force -ErrorAction Stop
            }
        }
        
        # Verify write access (appends empty string - fails if no write permission)
        [System.IO.File]::AppendAllText($$PrimaryLogFile, "")
        $$script:LogFilePath = $$PrimaryLogFile
        return
    } catch {
        # Fall through to fallback (directory creation, rotation, or write failed)
    }
    
    # Fallback location
    try {
        $$FallbackLogParent = Split-Path -Path $$FallbackLogFile -Parent
        if (-not (Test-Path -Path $$FallbackLogParent)) {
            New-Item -Path $$FallbackLogParent -ItemType Directory -Force -ErrorAction Stop | Out-Null
        }
        
        if (Test-Path -Path $$FallbackLogFile) {
            $$LogSize = (Get-Item $$FallbackLogFile).Length
            $$MaxSize = ${log_rotation_mb} * 1024 * 1024
            if ($$LogSize -ge $$MaxSize) {
                $$OldLogFile = "$$FallbackLogFile.old"
                if (Test-Path $$OldLogFile) { Remove-Item $$OldLogFile -Force -ErrorAction Stop }
                Move-Item -Path $$FallbackLogFile -Destination $$OldLogFile -Force -ErrorAction Stop
            }
        }
        
        [System.IO.File]::AppendAllText($$FallbackLogFile, "")
        $$script:LogFilePath = $$FallbackLogFile
    } catch {
        # All log locations failed - log warning to stderr and continue
        Write-Warning "NAPT Requirements: Failed to initialize logging (primary and fallback locations unavailable). Script will continue but no log file will be created."
        $$script:LogFilePath = $$null
    }
}

# Check if registry entry is MSI-based installation
function Test-IsMSIInstallation {
    param(
        [Microsoft.Win32.RegistryKey]$$RegKey
    )
    
    # Check WindowsInstaller DWORD value - set automatically by Windows Installer
    # for all MSI installations. This is the authoritative indicator.
    try {
        $$WindowsInstaller = $$RegKey.GetValue("WindowsInstaller")
        return ($$WindowsInstaller -eq 1)
    } catch {
        return $$false
    }
}

# Get registry keys using explicit RegistryView for deterministic behavior
# This works regardless of PowerShell process bitness
function Get-UninstallKeys {
    param(
        [Microsoft.Win32.RegistryHive]$$Hive,
        [Microsoft.Win32.RegistryView]$$View,
        [string]$$ViewName
    )
    
    $$Results = @()
    $$UninstallPath = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    
    try {
        $$BaseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($$Hive, $$View)
        $$UninstallKey = $$BaseKey.OpenSubKey($$UninstallPath)
        
        if ($$UninstallKey) {
            foreach ($$SubKeyName in $$UninstallKey.GetSubKeyNames()) {
                try {
                    $$SubKey = $$UninstallKey.OpenSubKey($$SubKeyName)
                    if ($$SubKey) {
                        $$Results += @{
                            Key = $$SubKey
                            Hive = $$Hive
                            View = $$ViewName
                            Path = "$$($$(if ($$Hive -eq [Microsoft.Win32.RegistryHive]::LocalMachine) { 'HKLM' } else { 'HKCU' })):\\$$UninstallPath\\$$SubKeyName"
                        }
                    }
                } catch {
                    # Skip keys we can't open
                }
            }
        }
        
        # Note: Don't close BaseKey/UninstallKey here as SubKeys are still in use
    } catch {
        Write-CMTraceLog -Message "[Requirements] Error opening registry: $$Hive $$ViewName - $$($$_.Exception.Message)" -Type "WARNING"
    }
    
    return $$Results
}

# Version comparison function - returns true if Installed < Target
function Compare-VersionLessThan {
    param(
        [string]$$InstalledVersion,
        [string]$$TargetVersion
    )
    
    # Parse version parts
    $$InstalledParts = $$InstalledVersion -split '[.\\-]' | ForEach-Object { [int]$$_ }
    $$TargetParts = $$TargetVersion -split '[.\\-]' | ForEach-Object { [int]$$_ }
    
    $$MaxLength = [Math]::Max($$InstalledParts.Count, $$TargetParts.Count)
    
    for ($$i = 0; $$i -lt $$MaxLength; $$i++) {
        $$InstalledPart = if ($$i -lt $$InstalledParts.Count) { $$InstalledParts[$$i] } else { 0 }
        $$TargetPart = if ($$i -lt $$TargetParts.Count) { $$TargetParts[$$i] } else { 0 }
        
        if ($$InstalledPart -lt $$TargetPart) {
            return $$true
        }
        if ($$InstalledPart -gt $$TargetPart) {
            return $$false
        }
    }
    
    return $$false  # Versions are equal, so not less than
}

# Main requirements logic
Initialize-LogFile

# Build component identifier from app name and version (sanitized for valid identifier)
$$SanitizedAppName = $$AppName -replace '[^a-zA-Z0-9]', '-' -replace '-+', '-' -replace '^-|-$$', ''
$$script:ComponentName = "$$SanitizedAppName-$$TargetVersion-Requirements"

Write-CMTraceLog -Message "[Initialization] Requirements script running as user: $$($$script:CurrentIdentity.Name)" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] Starting requirements check for: $$AppName (Target: $$TargetVersion, Installer Type: $$(if ($$IsMSIInstaller) { 'MSI' } else { 'Non-MSI' }), Architecture: $$ExpectedArchitecture)" -Type "INFO"

# Detect OS architecture
$$Is64BitOS = [Environment]::Is64BitOperatingSystem

Write-CMTraceLog -Message "[Initialization] OS Architecture: $$(if ($$Is64BitOS) { '64-bit' } else { '32-bit' })" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] PowerShell Process: $$(if ([Environment]::Is64BitProcess) { '64-bit' } else { '32-bit' })" -Type "INFO"

# Build list of registry keys to check based on expected architecture
# Uses OpenBaseKey with explicit RegistryView for deterministic behavior
$$AllKeys = @()

# Determine which registry views to check based on architecture
$$CheckViews = @()

switch ($$ExpectedArchitecture.ToLower()) {
    "x64" {
        if (-not $$Is64BitOS) {
            Write-CMTraceLog -Message "[Requirements] Expected x64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
        } else {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
    }
    "arm64" {
        # ARM64 uses 64-bit registry view
        if (-not $$Is64BitOS) {
            Write-CMTraceLog -Message "[Requirements] Expected arm64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
        } else {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit (ARM64)" }
        }
    }
    "x86" {
        $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
    "any" {
        # Check both views (permissive mode)
        if ($$Is64BitOS) {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
        $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
    default {
        Write-CMTraceLog -Message "[Requirements] Unknown architecture '$$ExpectedArchitecture', defaulting to 'any'" -Type "WARNING"
        if ($$Is64BitOS) {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
        $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
}

# Build literal registry paths for logging (matches actual paths opened by OpenBaseKey per view)
$$RegPathDescriptions = @()
foreach ($$ViewInfo in $$CheckViews) {
    if ($$ViewInfo.Name -like '64-bit*') {
        $$RegPathDescriptions += "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        $$RegPathDescriptions += "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    } else {
        if ($$Is64BitOS) {
            $$RegPathDescriptions += "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
            $$RegPathDescriptions += "HKCU:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        } else {
            $$RegPathDescriptions += "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
            $$RegPathDescriptions += "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        }
    }
}
Write-CMTraceLog -Message "[Initialization] Registry paths to check: $$($$RegPathDescriptions -join ', ')" -Type "INFO"

# Collect all registry keys from selected views
foreach ($$ViewInfo in $$CheckViews) {
    # HKLM (machine-level installations)
    $$AllKeys += Get-UninstallKeys -Hive ([Microsoft.Win32.RegistryHive]::LocalMachine) -View $$ViewInfo.View -ViewName $$ViewInfo.Name
    # HKCU (user-level installations)
    $$AllKeys += Get-UninstallKeys -Hive ([Microsoft.Win32.RegistryHive]::CurrentUser) -View $$ViewInfo.View -ViewName $$ViewInfo.Name
}

Write-CMTraceLog -Message "[Initialization] Found $$($$AllKeys.Count) registry keys to check" -Type "INFO"

$$FoundOlderVersion = $$false
$$InstalledVersion = $$null
$$DisplayName = $$null

# Check all registry keys to find matching DisplayName and version
foreach ($$KeyInfo in $$AllKeys) {
    try {
        $$Key = $$KeyInfo.Key
        $$DisplayNameValue = $$Key.GetValue("DisplayName")
        $$VersionValue = $$Key.GetValue("DisplayVersion")
        
        if ($$DisplayNameValue ${display_name_operator} $$AppName) {
            $$RegKeyPath = $$KeyInfo.Path
            
            # Check if installer type matches (MSI vs non-MSI)
            # MSI installers: strict matching - only accept MSI registry entries
            # Non-MSI installers: permissive - accept any entry (EXEs may use embedded MSIs)
            $$IsMSIEntry = Test-IsMSIInstallation -RegKey $$Key
            if ($$IsMSIInstaller -and -not $$IsMSIEntry) {
                # Building from MSI, but registry entry is not MSI - skip
                Write-CMTraceLog -Message "[Requirements] Type mismatch: $$DisplayNameValue (Found: Non-MSI, Expected: MSI, Path: $$RegKeyPath)" -Type "INFO"
                continue
            }
            # Note: Non-MSI installers accept ANY registry entry (MSI or non-MSI)
            # because EXE installers often wrap embedded MSIs that set WindowsInstaller=1
            
            $$DisplayName = $$DisplayNameValue
            $$InstalledVersion = $$VersionValue

            Write-CMTraceLog -Message "[Requirements] Match found: $$DisplayName (Found: $$(if ($$InstalledVersion) { $$InstalledVersion } else { 'None' }), Type: $$(if ($$IsMSIEntry) { 'MSI' } else { 'Non-MSI' }), Arch: $$($KeyInfo.View), Path: $$RegKeyPath)" -Type "INFO"

            if ($$InstalledVersion) {
                if (Compare-VersionLessThan -InstalledVersion $$InstalledVersion -TargetVersion $$TargetVersion) {
                    Write-CMTraceLog -Message "[Requirements] Version check passed: $$InstalledVersion < $$TargetVersion" -Type "INFO"
                    $$FoundOlderVersion = $$true
                    break
                } else {
                    Write-CMTraceLog -Message "[Requirements] Version check not met: $$InstalledVersion >= $$TargetVersion" -Type "INFO"
                }
            } else {
                Write-CMTraceLog -Message "[Requirements] No version found: $$DisplayName (Path: $$RegKeyPath)" -Type "WARNING"
            }
        }
    } catch {
        Write-CMTraceLog -Message "[Requirements] Error checking registry path $$($KeyInfo.Path) : $$($$_.Exception.Message)" -Type "ERROR"
    }
}

# Always exit 0 - Intune evaluates STDOUT
if ($$FoundOlderVersion) {
    Write-CMTraceLog -Message "[Result] Update Required: $$AppName (Found: $$InstalledVersion, Expected: < $$TargetVersion, Type: $$(if ($$IsMSIInstaller) { 'MSI' } else { 'Non-MSI' }), Arch: $$ExpectedArchitecture)" -Type "INFO"
    Write-Output "Required"
    exit 0
} else {
    $$FoundVersion = if ($$InstalledVersion) { $$InstalledVersion } else { "None" }
    Write-CMTraceLog -Message "[Result] Update Not Required: $$AppName (Found: $$FoundVersion, Expected: < $$TargetVersion, Type: $$(if ($$IsMSIInstaller) { 'MSI' } else { 'Non-MSI' }), Arch: $$ExpectedArchitecture)" -Type "WARNING"
    # Output nothing - requirement not met
    exit 0
}
"""


def generate_requirements_script(config: RequirementsConfig, output_path: Path) -> Path:
    """Generate PowerShell requirements script for Intune Win32 app.

    Creates a PowerShell script that checks Windows uninstall registry keys
    for software installation and determines if an older version is installed.
    The script outputs "Required" if installed version < target version,
    nothing otherwise. Always exits with code 0 so Intune can evaluate STDOUT.

    Args:
        config: Requirements configuration (app name, version, logging settings).
        output_path: Path where the requirements script will be saved.

    Returns:
        Path to the generated requirements script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from notapkgtool.requirements import RequirementsConfig, generate_requirements_script

            config = RequirementsConfig(
                app_name="Google Chrome",
                version="131.0.6778.86",
            )
            script_path = generate_requirements_script(
                config,
                Path("requirements.ps1")
            )
            ```

    Note:
        The script is saved with UTF-8 BOM encoding for proper PowerShell
        execution on Windows systems.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose(
        "REQUIREMENTS", f"Generating requirements script: {output_path.name}"
    )

    # Generate script content from template
    # Use safe_substitute() so PowerShell variables ($$Variable) are preserved
    # as $Variable without raising KeyError for missing placeholders
    script_content = string.Template(_REQUIREMENTS_SCRIPT_TEMPLATE).safe_substitute(
        app_name=config.app_name,
        version=config.version,
        log_rotation_mb=config.log_rotation_mb,
        is_msi_installer="$True" if config.is_msi_installer else "$False",
        expected_architecture=config.expected_architecture,
        display_name_operator="-like" if config.use_wildcard else "-eq",
    )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write script with UTF-8 BOM encoding (required for PowerShell)
    try:
        script_bytes = script_content.encode("utf-8-sig")
        output_path.write_bytes(script_bytes)
        logger.verbose("REQUIREMENTS", f"Requirements script written to: {output_path}")
    except OSError as err:
        raise OSError(
            f"Failed to write requirements script to {output_path}: {err}"
        ) from err

    return output_path
