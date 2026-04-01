# CMTrace log format function
function Write-CMTraceLog {
    param(
        [string]$Message,
        [string]$Component = $script:ComponentName,
        [string]$Type = "INFO"  # "INFO", "WARNING", "ERROR", "DEBUG"
    )

    $LogFile = $script:LogFilePath

    if (-not $LogFile) {
        return
    }

    # Convert string log level to CMTrace numeric type
    # 1=Info, 2=Warning, 3=Error, 4=Debug
    $TypeNumber = switch ($Type.ToUpper()) {
        "INFO" { 1 }
        "WARNING" { 2 }
        "ERROR" { 3 }
        "DEBUG" { 4 }
        default { 1 }  # Default to INFO if unknown
    }

    # Format time: HH:mm:ss.fff-offset (offset in minutes, e.g., -480 for -08:00)
    $Now = [DateTimeOffset](Get-Date)
    $TimeFormatted = $Now.ToString("HH:mm:ss.fff")
    $OffsetMinutes = [int]$Now.Offset.TotalMinutes
    $TimeWithOffset = "$TimeFormatted$OffsetMinutes"

    # Format date: M-d-yyyy (single digit month/day when appropriate)
    $DateFormatted = $Now.ToString("M-d-yyyy")

    # Get context (user identity name) and script file path
    $ContextName = if ($script:CurrentIdentity) { $script:CurrentIdentity.Name } else { "UNKNOWN" }
    $ScriptFile = if ($MyInvocation.ScriptName) { $MyInvocation.ScriptName } else { "$NaptFallbackScriptName" }

    $Line = "<![LOG[$Message]LOG]!><time=""$TimeWithOffset"" date=""$DateFormatted"" component=""$Component"" context=""$ContextName"" type=""$TypeNumber"" thread=""$PID"" file=""$ScriptFile"">"

    try {
        Add-Content -Path $LogFile -Value $Line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {
        # Silently fail if we can't write to log
    }
}

# Determine log file location
function Initialize-LogFile {
    $script:CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $IsSystemContext = $script:CurrentIdentity.Name -eq "NT AUTHORITY\SYSTEM"

    if ($IsSystemContext) {
        # System context - try Intune log folder first
        $PrimaryLogDir = "C:\ProgramData\Microsoft\IntuneManagementExtension\Logs"
        $PrimaryLogFile = Join-Path $PrimaryLogDir "$NaptLogBaseName.log"
        $FallbackLogDir = "C:\ProgramData\NAPT"
        $FallbackLogFile = Join-Path $FallbackLogDir "$NaptLogBaseName.log"
    } else {
        # User context
        $PrimaryLogDir = "C:\ProgramData\Microsoft\IntuneManagementExtension\Logs"
        $PrimaryLogFile = Join-Path $PrimaryLogDir "$NaptLogBaseNameUser.log"
        $FallbackLogDir = $env:LOCALAPPDATA
        $FallbackLogFile = Join-Path $FallbackLogDir "NAPT\$NaptLogBaseNameUser.log"
    }

    # Try primary location first
    try {
        # Ensure parent directory exists (fails with -ErrorAction Stop if no perms)
        $PrimaryLogParent = Split-Path -Path $PrimaryLogFile -Parent
        if (-not (Test-Path -Path $PrimaryLogParent)) {
            New-Item -Path $PrimaryLogParent -ItemType Directory -Force -ErrorAction Stop | Out-Null
        }

        # Handle log rotation if needed
        if (Test-Path -Path $PrimaryLogFile) {
            $LogSize = (Get-Item $PrimaryLogFile).Length
            $MaxSize = $NaptLogRotationMb * 1024 * 1024
            if ($LogSize -ge $MaxSize) {
                $OldLogFile = "$PrimaryLogFile.old"
                if (Test-Path $OldLogFile) { Remove-Item $OldLogFile -Force -ErrorAction Stop }
                Move-Item -Path $PrimaryLogFile -Destination $OldLogFile -Force -ErrorAction Stop
            }
        }

        # Verify write access (appends empty string - fails if no write permission)
        [System.IO.File]::AppendAllText($PrimaryLogFile, "")
        $script:LogFilePath = $PrimaryLogFile
        return
    } catch {
        # Fall through to fallback (directory creation, rotation, or write failed)
    }

    # Fallback location
    try {
        $FallbackLogParent = Split-Path -Path $FallbackLogFile -Parent
        if (-not (Test-Path -Path $FallbackLogParent)) {
            New-Item -Path $FallbackLogParent -ItemType Directory -Force -ErrorAction Stop | Out-Null
        }

        if (Test-Path -Path $FallbackLogFile) {
            $LogSize = (Get-Item $FallbackLogFile).Length
            $MaxSize = $NaptLogRotationMb * 1024 * 1024
            if ($LogSize -ge $MaxSize) {
                $OldLogFile = "$FallbackLogFile.old"
                if (Test-Path $OldLogFile) { Remove-Item $OldLogFile -Force -ErrorAction Stop }
                Move-Item -Path $FallbackLogFile -Destination $OldLogFile -Force -ErrorAction Stop
            }
        }

        [System.IO.File]::AppendAllText($FallbackLogFile, "")
        $script:LogFilePath = $FallbackLogFile
    } catch {
        # All log locations failed - log warning to stderr and continue
        Write-Warning "NAPT [$NaptScriptType] Failed to initialize logging (primary and fallback locations unavailable). Script will continue but no log file will be created."
        $script:LogFilePath = $null
    }
}

# Check if registry entry is MSI-based installation
function Test-IsMSIInstallation {
    param(
        [Microsoft.Win32.RegistryKey]$RegKey
    )

    # Check WindowsInstaller DWORD value - set automatically by Windows Installer
    # for all MSI installations. This is the authoritative indicator.
    try {
        $WindowsInstaller = $RegKey.GetValue("WindowsInstaller")
        return ($WindowsInstaller -eq 1)
    } catch {
        return $false
    }
}

# Get registry keys using explicit RegistryView for deterministic behavior
# This works regardless of PowerShell process bitness
function Get-UninstallKeys {
    param(
        [Microsoft.Win32.RegistryHive]$Hive,
        [Microsoft.Win32.RegistryView]$View,
        [string]$ViewName
    )

    $Results = @()
    $UninstallPath = "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

    try {
        $BaseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, $View)
        $UninstallKey = $BaseKey.OpenSubKey($UninstallPath)

        if ($UninstallKey) {
            foreach ($SubKeyName in $UninstallKey.GetSubKeyNames()) {
                try {
                    $SubKey = $UninstallKey.OpenSubKey($SubKeyName)
                    if ($SubKey) {
                        $Results += @{
                            Key = $SubKey
                            Hive = $Hive
                            View = $ViewName
                            Path = "$($( if ($Hive -eq [Microsoft.Win32.RegistryHive]::LocalMachine) { 'HKLM' } else { 'HKCU' } )):\$UninstallPath\$SubKeyName"
                        }
                    }
                } catch {
                    # Skip keys we can't open
                }
            }
        }

        # Note: Don't close BaseKey/UninstallKey here as SubKeys are still in use
    } catch {
        Write-CMTraceLog -Message "[$NaptScriptType] Error opening registry: $Hive $ViewName - $($_.Exception.Message)" -Type "WARNING"
    }

    return $Results
}
