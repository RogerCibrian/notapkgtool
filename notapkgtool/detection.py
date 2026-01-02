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

    """

    app_name: str
    version: str
    log_format: LogFormat = "cmtrace"
    log_level: LogLevel = "INFO"
    log_rotation_mb: int = 3
    exact_match: bool = True
    app_id: str = ""


def sanitize_filename(name: str, app_id: str = "") -> str:
    """Sanitize string for use in Windows filename.

    Rules:
        - Replace spaces with hyphens
        - Remove invalid Windows filename characters (< > : " | ? * \ /)
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

param(
    [string]$AppName = "${app_name}",
    [string]$ExpectedVersion = "${version}",
    [bool]$ExactMatch = ${exact_match}
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
    $$IsSystemContext = $$script:CurrentIdentity.Name -eq "NT AUTHORITY\SYSTEM"
    
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
    $$InstalledParts = $$InstalledVersion -split '[.\-]' | ForEach-Object { [int]$$_ }
    $$ExpectedParts = $$ExpectedVersion -split '[.\-]' | ForEach-Object { [int]$$_ }
    
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
$$script:ComponentName = "$$SanitizedAppName-$$ExpectedVersion"

Write-CMTraceLog -Message "[Initialization] Detection script running as user: $$($$script:CurrentIdentity.Name)" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] Starting detection for: $$AppName (Expected: $$ExpectedVersion, Mode: $$(if ($$ExactMatch) { 'Exact Match' } else { 'Minimum Version' }))" -Type "INFO"

# Detect if PowerShell is running as 64-bit process
$$Is64BitProcess = [Environment]::Is64BitProcess

# Detect OS architecture
$$OSArchitecture = (Get-CimInstance -ClassName Win32_OperatingSystem).OSArchitecture
$$Is64BitOS = $$OSArchitecture -eq "64-bit"

Write-CMTraceLog -Message "[Initialization] OS Architecture: $$OSArchitecture" -Type "INFO"
Write-CMTraceLog -Message "[Initialization] PowerShell Process: $$(if ($$Is64BitProcess) { '64-bit' } else { '32-bit' })" -Type "INFO"

# Build registry paths based on process and OS architecture
$$RegPaths = @(
    # Machine-level native path (always check)
    # HKLM contains per-machine installations (requires admin/system context)
    "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
)

# User-level native path (always check)
# HKCU contains per-user installations (visible in user context)
$$RegPaths += "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"

# Wow6432Node paths (only for 64-bit process on 64-bit OS)
# On 64-bit Windows, 32-bit processes are redirected to Wow6432Node by the registry.
# A 64-bit process must explicitly check Wow6432Node to see 32-bit app entries.
# A 32-bit process cannot access the native 64-bit SOFTWARE key, so checking
# Wow6432Node would be redundant.
if ($$Is64BitOS -and $$Is64BitProcess) {
    $$RegPaths += "HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    $$RegPaths += "HKCU:\\SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
}

Write-CMTraceLog -Message "[Initialization] Registry paths to check: $$($$RegPaths -join ', ')" -Type "INFO"

$$Found = $$false
$$InstalledVersion = $$null
$$DisplayName = $$null

# Check all registry paths to find matching DisplayName and version
foreach ($$RegPath in $$RegPaths) {
    try {
        $$Keys = Get-ChildItem -Path $$RegPath -ErrorAction SilentlyContinue
        foreach ($$Key in $$Keys) {
            $$DisplayNameValue = (Get-ItemProperty -Path $$Key.PSPath -Name "DisplayName" -ErrorAction SilentlyContinue).DisplayName
            $$VersionValue = (Get-ItemProperty -Path $$Key.PSPath -Name "DisplayVersion" -ErrorAction SilentlyContinue).DisplayVersion
            
            if ($$DisplayNameValue -eq $$AppName) {
                $$DisplayName = $$DisplayNameValue
                $$InstalledVersion = $$VersionValue
                
                Write-CMTraceLog -Message "[Detection] Found matching DisplayName in registry path '$$RegPath': $$DisplayName (Installed Version: $$InstalledVersion)" -Type "INFO"
                
                if ($$InstalledVersion) {
                    if (Compare-Version -InstalledVersion $$InstalledVersion -ExpectedVersion $$ExpectedVersion -ExactMatch $$ExactMatch) {
                        Write-CMTraceLog -Message "[Detection] Version check PASSED: Installed version $$InstalledVersion $$(if ($$ExactMatch) { 'exactly matches' } else { 'meets or exceeds' }) expected version $$ExpectedVersion" -Type "INFO"
                        $$Found = $$true
                        break
                    } else {
                        Write-CMTraceLog -Message "[Detection] Version check FAILED: Installed version $$InstalledVersion $$(if ($$ExactMatch) { 'does not exactly match' } else { 'is less than' }) expected version $$ExpectedVersion" -Type "INFO"
                    }
                } else {
                    Write-CMTraceLog -Message "[Detection] DisplayName '$$DisplayName' found in registry path '$$RegPath' but no DisplayVersion value is present" -Type "WARNING"
                }
            }
        }
        if ($$Found) {
            break
        }
    } catch {
        Write-CMTraceLog -Message "[Detection] Error checking registry path $$RegPath : $$($$_.Exception.Message)" -Type "ERROR"
    }
}

if ($$Found) {
    Write-CMTraceLog -Message "[Result] Detection SUCCESS: $$AppName (version $$InstalledVersion) is installed and meets version requirements (Expected: $$ExpectedVersion, Match Type: $$(if ($$ExactMatch) { 'Exact' } else { 'Minimum' }))" -Type "INFO"
    Write-Output "Installed"
    exit 0
} else {
    Write-CMTraceLog -Message "[Result] Detection FAILED: $$AppName not found in registry paths or installed version does not meet requirements (Expected: $$ExpectedVersion, Match Type: $$(if ($$ExactMatch) { 'Exact' } else { 'Minimum' }))" -Type "INFO"
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
