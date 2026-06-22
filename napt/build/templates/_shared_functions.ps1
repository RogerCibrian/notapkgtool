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

    # Format time: HH:mm:ss.fff+bias. ConfigMgr bias is UTC minus local time
    # in minutes with an explicit sign (e.g., +480 for UTC-8, -120 for UTC+2).
    $Now = [DateTimeOffset](Get-Date)
    $TimeFormatted = $Now.ToString("HH:mm:ss.fff")
    $BiasMinutes = -[int]$Now.Offset.TotalMinutes
    $TimeWithOffset = "$TimeFormatted$($BiasMinutes.ToString('+000;-000'))"

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

# Parse a version string into numeric parts. Each '.'- or '-'-separated
# segment contributes its leading digits; segments without leading digits
# count as 0, so prerelease identifiers are not ranked ("1.2.3-beta"
# parses the same as "1.2.3.0").
function ConvertTo-VersionParts {
    param(
        [string]$Version
    )

    $Parts = @()
    $HasNonNumeric = $false

    foreach ($Segment in ($Version -split '[.\-]')) {
        if ($Segment -match '^(\d+)') {
            $Parts += [int64]$Matches[1]
            if ($Segment -ne $Matches[1]) { $HasNonNumeric = $true }
        } else {
            $Parts += [int64]0
            $HasNonNumeric = $true
        }
    }

    if ($HasNonNumeric) {
        Write-CMTraceLog -Message "[$NaptScriptType] Version '$Version' contains non-numeric segments, comparing as '$($Parts -join '.')'" -Type "WARNING"
    }

    return ,$Parts
}

# Compare two version strings numerically. Returns -1 if Left < Right,
# 0 if equal, 1 if Left > Right. Missing trailing parts count as 0.
function Compare-VersionString {
    param(
        [string]$LeftVersion,
        [string]$RightVersion
    )

    $LeftParts = ConvertTo-VersionParts -Version $LeftVersion
    $RightParts = ConvertTo-VersionParts -Version $RightVersion

    $MaxLength = [Math]::Max($LeftParts.Count, $RightParts.Count)

    for ($i = 0; $i -lt $MaxLength; $i++) {
        $LeftPart = if ($i -lt $LeftParts.Count) { $LeftParts[$i] } else { [int64]0 }
        $RightPart = if ($i -lt $RightParts.Count) { $RightParts[$i] } else { [int64]0 }

        if ($LeftPart -gt $RightPart) { return 1 }
        if ($LeftPart -lt $RightPart) { return -1 }
    }

    return 0
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
