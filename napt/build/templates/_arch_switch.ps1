switch ($ExpectedArchitecture.ToLower()) {
    "x64" {
        if (-not $Is64BitOS) {
            Write-CMTraceLog -Message "[$NaptScriptType] Expected x64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
        } else {
            $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
    }
    "arm64" {
        # ARM64 uses 64-bit registry view
        if (-not $Is64BitOS) {
            Write-CMTraceLog -Message "[$NaptScriptType] Expected arm64 architecture but running on 32-bit OS - app cannot be installed" -Type "WARNING"
        } else {
            $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit (ARM64)" }
        }
    }
    "x86" {
        $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
    "any" {
        # Check both views (permissive mode)
        if ($Is64BitOS) {
            $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
        $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
    default {
        Write-CMTraceLog -Message "[$NaptScriptType] Unknown architecture '$ExpectedArchitecture', defaulting to 'any'" -Type "WARNING"
        if ($Is64BitOS) {
            $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry64; Name = "64-bit" }
        }
        $CheckViews += @{ View = [Microsoft.Win32.RegistryView]::Registry32; Name = "32-bit" }
    }
}

# Build literal registry paths for logging (matches actual paths opened by OpenBaseKey per view)
$RegPathDescriptions = @()
foreach ($ViewInfo in $CheckViews) {
    if ($ViewInfo.Name -like '64-bit*') {
        $RegPathDescriptions += "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        $RegPathDescriptions += "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    } else {
        if ($Is64BitOS) {
            $RegPathDescriptions += "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
            $RegPathDescriptions += "HKCU:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        } else {
            $RegPathDescriptions += "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            $RegPathDescriptions += "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        }
    }
}
Write-CMTraceLog -Message "[Initialization] Registry paths to check: $($RegPathDescriptions -join ', ')" -Type "INFO"
