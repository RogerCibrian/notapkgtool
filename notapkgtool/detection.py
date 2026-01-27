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

"""Detection script generation for Intune Win32 apps.

This module generates PowerShell detection scripts for Intune Win32 app
deployments. Scripts check Windows uninstall registry keys for installed
software and version information using CMTrace-formatted logging.

Detection Logic:
    - Checks HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall (always)
    - Checks HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Checks HKCU:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
        (only on 64-bit OS with 64-bit PowerShell process)
    - Matches by DisplayName (using AppName from recipe or MSI ProductName)
    - Compares version (exact or minimum version match based on config)
    - Provides verbose logging with detailed detection results, registry paths,
        installed vs expected versions, and match type information

Installer Type Filtering:
    Scripts filter registry entries based on installer type to prevent false
    matches when both MSI and EXE versions of software exist:

    - MSI installers (strict): Only matches registry entries with
        WindowsInstaller=1. Prevents false matches with EXE versions.
    - Non-MSI installers (permissive): Matches ANY registry entry. Handles
        EXE installers that run embedded MSIs internally.

Logging:
    - Primary (System): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTDetections.log
    - Primary (User): C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs\\NAPTDetectionsUser.log
    - Fallback (System): C:\\ProgramData\\NAPT\\NAPTDetections.log
    - Fallback (User): %LOCALAPPDATA%\\NAPT\\NAPTDetectionsUser.log
    - Log rotation: 2-file rotation (.log and .log.old), configurable max size
        (default: 3MB)
    - Format: CMTrace format for compatibility with Intune diagnostics
    - Features: Write permission testing with automatic fallback to alternate
        locations, verbose component-based logging with dynamic component names
        based on app name and version, detailed detection workflow logging

Example:
    Generate detection script:
        ```python
        from pathlib import Path
        from notapkgtool.detection import DetectionConfig, generate_detection_script

        config = DetectionConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
            log_format="cmtrace",
            log_level="INFO",
        )
        script_path = generate_detection_script(
            config=config,
            output_path=Path("builds/chrome/131.0.6778.86/Google-Chrome-131.0.6778.86-Detection.ps1"),
        )
        ```

Note:
    Detection scripts are saved as siblings to the packagefiles directory
    to prevent them from being included in the .intunewin package. They
    should be uploaded separately to Intune alongside the package.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import string
from typing import Literal

LogFormat = Literal["cmtrace"]
LogLevel = Literal["INFO", "WARNING", "ERROR", "DEBUG"]


# Type alias for architecture values
ArchitectureMode = Literal["x86", "x64", "arm64", "any"]


@dataclass(frozen=True)
class DetectionConfig:
    """Configuration for detection script generation.

    Attributes:
        app_name: Application name to search for in registry DisplayName.
        version: Expected version string to match.
        log_format: Log format (currently only "cmtrace" supported).
        log_level: Minimum log level (INFO, WARNING, ERROR, DEBUG).
        log_rotation_mb: Maximum log file size in MB before rotation.
        exact_match: If True, version must match exactly. If False, minimum
            version comparison (remote >= expected).
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

    """

    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    exact_match: bool = False
    app_id: str = ""
    is_msi_installer: bool = False
    expected_architecture: ArchitectureMode = "any"


def sanitize_filename(name: str, app_id: str = "") -> str:
    """Sanitize string for use in Windows filename.

    Rules:
        - Replace spaces with hyphens
        - Remove invalid Windows filename characters (< > : " | ? * \\ /)
        - Normalize multiple consecutive hyphens to single hyphen
        - Remove leading/trailing hyphens and dots
        - If result is empty, fallback to app_id (or "app" if app_id is empty)

    Args:
        name: String to sanitize (e.g., "Google Chrome").
        app_id: Fallback identifier if name becomes empty after sanitization.

    Returns:
        Sanitized filename-safe string (e.g., "Google-Chrome").

    Example:
        Basic sanitization:
            ```python
            sanitize_filename("Google Chrome")  # Returns: "Google-Chrome"
            sanitize_filename("My App v2.0")    # Returns: "My-App-v2.0"
            sanitize_filename("Test<>App")      # Returns: "TestApp"
            ```

        Fallback behavior:
            ```python
            sanitize_filename("  ", "my-app")   # Returns: "my-app"
            sanitize_filename("", "test")       # Returns: "test"
            ```

    """
    # Replace spaces with hyphens
    sanitized = name.replace(" ", "-")

    # Remove invalid Windows filename characters: < > : " | ? * \ /
    invalid_chars = '<>:"|?*\\/'
    for char in invalid_chars:
        sanitized = sanitized.replace(char, "")

    # Normalize multiple consecutive hyphens to single hyphen
    sanitized = re.sub(r"-+", "-", sanitized)

    # Remove leading/trailing hyphens and dots
    sanitized = sanitized.strip(".-")

    # Fallback to app_id if empty
    if not sanitized:
        sanitized = app_id if app_id else "app"

    return sanitized


# PowerShell detection script template
_DETECTION_SCRIPT_TEMPLATE = """# Detection script for ${app_name} ${version}
# Generated by NAPT (Not a Package Tool)
# This script checks Windows uninstall registry keys for software installation.
# Uses explicit registry views for deterministic architecture-aware detection.

param(
    [string]$$AppName = "${app_name}",
    [string]$$ExpectedVersion = "${version}",
    [bool]$$ExactMatch = ${exact_match},
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
    $$ScriptFile = if ($$MyInvocation.ScriptName) { $$MyInvocation.ScriptName } else { "detection.ps1" }
    
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
        $$PrimaryLogFile = Join-Path $$PrimaryLogDir "NAPTDetections.log"
        $$FallbackLogDir = "C:\\ProgramData\\NAPT"
        $$FallbackLogFile = Join-Path $$FallbackLogDir "NAPTDetections.log"
    } else {
        # User context
        $$PrimaryLogDir = "C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs"
        $$PrimaryLogFile = Join-Path $$PrimaryLogDir "NAPTDetectionsUser.log"
        $$FallbackLogDir = $$env:LOCALAPPDATA
        $$FallbackLogFile = Join-Path $$FallbackLogDir "NAPT\\NAPTDetectionsUser.log"
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
        Write-Warning "NAPT Detection: Failed to initialize logging (primary and fallback locations unavailable). Detection will continue but no log file will be created."
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
        Write-CMTraceLog -Message "[Detection] Error opening registry: $$Hive $$ViewName - $$($$_.Exception.Message)" -Type "WARNING"
    }
    
    return $$Results
}

# Version comparison function
function Compare-Version {
    param(
        [string]$$InstalledVersion,
        [string]$$ExpectedVersion,
        [bool]$$ExactMatch
    )
    
    if ($$ExactMatch) {
        return $$InstalledVersion -eq $$ExpectedVersion
    }
    
    # Minimum version comparison (installed >= expected)
    $$InstalledParts = $$InstalledVersion -split '[.\\-]' | ForEach-Object { [int]$$_ }
    $$ExpectedParts = $$ExpectedVersion -split '[.\\-]' | ForEach-Object { [int]$$_ }
    
    $$MaxLength = [Math]::Max($$InstalledParts.Count, $$ExpectedParts.Count)
    
    for ($$i = 0; $$i -lt $$MaxLength; $$i++) {
        $$InstalledPart = if ($$i -lt $$InstalledParts.Count) { $$InstalledParts[$$i] } else { 0 }
        $$ExpectedPart = if ($$i -lt $$ExpectedParts.Count) { $$ExpectedParts[$$i] } else { 0 }
        
        if ($$InstalledPart -gt $$ExpectedPart) {
            return $$true
        }
        if ($$InstalledPart -lt $$ExpectedPart) {
            return $$false
        }
    }
    
    return $$true  # Versions are equal
}

# Main detection logic
Initialize-LogFile

# Build component identifier from app name and version (sanitized for valid identifier)
$$SanitizedAppName = $$AppName -replace '[^a-zA-Z0-9]', '-' -replace '-+', '-' -replace '^-|-$', ''
$$script:ComponentName = "$$SanitizedAppName-$$ExpectedVersion-Detection"

Write-CMTraceLog -Message "[Initialization] Detection script running as user: $$($$script:CurrentIdentity.Name)" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] Starting detection check for: $$AppName (Expected: $$ExpectedVersion, Mode: $$(if ($$ExactMatch) { 'Exact Match' } else { 'Minimum Version' }), Installer Type: $$(if ($$IsMSIInstaller) { 'MSI' } else { 'Non-MSI' }), Architecture: $$ExpectedArchitecture)" -Type "INFO"

# Detect OS architecture
$$Is64BitOS = [Environment]::Is64BitOperatingSystem

Write-CMTraceLog -Message "[Initialization] OS: $$(if ($$Is64BitOS) { '64-bit' } else { '32-bit' }), PowerShell: $$(if ([Environment]::Is64BitProcess) { '64-bit' } else { '32-bit' })" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] Using explicit RegistryView for deterministic detection (architecture: $$ExpectedArchitecture)" -Type "INFO"

# Build list of registry keys to check based on expected architecture
# Uses OpenBaseKey with explicit RegistryView for deterministic behavior
$$AllKeys = @()

# Determine which registry views to check based on architecture
$$CheckViews = @()

switch ($$ExpectedArchitecture.ToLower()) {
    "x64" {
        if (-not $$Is64BitOS) {
            Write-CMTraceLog -Message "[Detection] Expected x64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
        } else {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
    }
    "arm64" {
        # ARM64 uses 64-bit registry view
        if (-not $$Is64BitOS) {
            Write-CMTraceLog -Message "[Detection] Expected arm64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
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
        Write-CMTraceLog -Message "[Detection] Unknown architecture '$$ExpectedArchitecture', defaulting to 'any'" -Type "WARNING"
        if ($$Is64BitOS) {
            $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
        $$CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
}

Write-CMTraceLog -Message "[Initialization] Registry views to check: $$($$CheckViews.Name -join ', ')" -Type "INFO"

# Collect all registry keys from selected views
foreach ($$ViewInfo in $$CheckViews) {
    # HKLM (machine-level installations)
    $$AllKeys += Get-UninstallKeys -Hive ([Microsoft.Win32.RegistryHive]::LocalMachine) -View $$ViewInfo.View -ViewName $$ViewInfo.Name
    # HKCU (user-level installations)
    $$AllKeys += Get-UninstallKeys -Hive ([Microsoft.Win32.RegistryHive]::CurrentUser) -View $$ViewInfo.View -ViewName $$ViewInfo.Name
}

Write-CMTraceLog -Message "[Initialization] Found $$($$AllKeys.Count) registry keys to check" -Type "INFO"

$$Found = $$false
$$InstalledVersion = $$null
$$DisplayName = $$null

# Check all registry keys to find matching DisplayName and version
foreach ($$KeyInfo in $$AllKeys) {
    try {
        $$Key = $$KeyInfo.Key
        $$DisplayNameValue = $$Key.GetValue("DisplayName")
        $$VersionValue = $$Key.GetValue("DisplayVersion")
        
        if ($$DisplayNameValue -eq $$AppName) {
            $$RegKeyPath = $$KeyInfo.Path
            
            # Check if installer type matches (MSI vs non-MSI)
            # MSI installers: strict matching - only accept MSI registry entries
            # Non-MSI installers: permissive - accept any entry (EXEs may use embedded MSIs)
            $$IsMSIEntry = Test-IsMSIInstallation -RegKey $$Key
            if ($$IsMSIInstaller -and -not $$IsMSIEntry) {
                # Building from MSI, but registry entry is not MSI - skip
                Write-CMTraceLog -Message "[Detection] Found matching DisplayName but installer type mismatch: '$$RegKeyPath' ($$($KeyInfo.View)) is non-MSI, expected MSI - skipping" -Type "INFO"
                continue
            }
            # Note: Non-MSI installers accept ANY registry entry (MSI or non-MSI)
            # because EXE installers often wrap embedded MSIs that set WindowsInstaller=1
            
            $$DisplayName = $$DisplayNameValue
            $$InstalledVersion = $$VersionValue
            
            Write-CMTraceLog -Message "[Detection] Found matching registry key: '$$RegKeyPath' (View: $$($KeyInfo.View), DisplayName: $$DisplayName, DisplayVersion: $$InstalledVersion, Installer Type: $$(if ($$IsMSIEntry) { 'MSI' } else { 'Non-MSI' }))" -Type "INFO"
            
            if ($$InstalledVersion) {
                if (Compare-Version -InstalledVersion $$InstalledVersion -ExpectedVersion $$ExpectedVersion -ExactMatch $$ExactMatch) {
                    Write-CMTraceLog -Message "[Detection] Version check PASSED: Installed version $$InstalledVersion $$(if ($$ExactMatch) { 'exactly matches' } else { 'meets or exceeds' }) expected version $$ExpectedVersion" -Type "INFO"
                    $$Found = $$true
                    break
                } else {
                    Write-CMTraceLog -Message "[Detection] Version check FAILED: Installed version $$InstalledVersion $$(if ($$ExactMatch) { 'does not exactly match' } else { 'is less than' }) expected version $$ExpectedVersion" -Type "INFO"
                }
            } else {
                Write-CMTraceLog -Message "[Detection] DisplayName '$$DisplayName' found in registry key '$$RegKeyPath' but no DisplayVersion value is present" -Type "WARNING"
            }
        }
    } catch {
        Write-CMTraceLog -Message "[Detection] Error checking registry key: $$($$_.Exception.Message)" -Type "ERROR"
    }
}

if ($$Found) {
    Write-CMTraceLog -Message "[Result] Detection SUCCESS: $$AppName (version $$InstalledVersion) is installed and meets version requirements (Expected: $$ExpectedVersion, Mode: $$(if ($$ExactMatch) { 'Exact Match' } else { 'Minimum Version' }))" -Type "INFO"
    Write-Output "Installed"
    exit 0
} else {
    Write-CMTraceLog -Message "[Result] Detection FAILED: $$AppName not found in registry paths or installed version does not meet requirements (Expected: $$ExpectedVersion, Mode: $$(if ($$ExactMatch) { 'Exact Match' } else { 'Minimum Version' }))" -Type "WARNING"
    exit 1
}
"""


def generate_detection_script(config: DetectionConfig, output_path: Path) -> Path:
    """Generate PowerShell detection script for Intune Win32 app.

    Creates a PowerShell script that checks Windows uninstall registry keys
    for software installation and version. The script uses CMTrace-formatted
    logging with verbose output, includes log rotation logic, and performs
    write permission testing with automatic fallback to alternate log locations
    if primary locations are unavailable.

    Args:
        config: Detection configuration (app name, version, logging settings).
        output_path: Path where the detection script will be saved.

    Returns:
        Path to the generated detection script.

    Raises:
        OSError: If the script file cannot be written.

    Example:
        Generate script with default settings:
            ```python
            from pathlib import Path
            from notapkgtool.detection import DetectionConfig, generate_detection_script

            config = DetectionConfig(
                app_name="Google Chrome",
                version="131.0.6778.86",
            )
            script_path = generate_detection_script(
                config,
                Path("detection.ps1")
            )
            ```

    Note:
        The script is saved with UTF-8 BOM encoding for proper PowerShell
        execution on Windows systems.

    """
    from notapkgtool.logging import get_global_logger

    logger = get_global_logger()

    logger.verbose("DETECTION", f"Generating detection script: {output_path.name}")

    # Generate script content from template
    # Use safe_substitute() so PowerShell variables ($$Variable) are preserved
    # as $Variable without raising KeyError for missing placeholders
    script_content = string.Template(_DETECTION_SCRIPT_TEMPLATE).safe_substitute(
        app_name=config.app_name,
        version=config.version,
        exact_match="$True" if config.exact_match else "$False",
        log_rotation_mb=config.log_rotation_mb,
        is_msi_installer="$True" if config.is_msi_installer else "$False",
        expected_architecture=config.expected_architecture,
    )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write script with UTF-8 BOM encoding (required for PowerShell)
    try:
        script_bytes = script_content.encode("utf-8-sig")
        output_path.write_bytes(script_bytes)
        logger.verbose("DETECTION", f"Detection script written to: {output_path}")
    except OSError as err:
        raise OSError(
            f"Failed to write detection script to {output_path}: {err}"
        ) from err

    return output_path
