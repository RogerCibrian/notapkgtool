# Retrieve a provisioned (all-users) AppX package by identity name.
function Get-InstalledAppxPackage {
    param(
        [string]$PackageIdentityName
    )

    try {
        $Provisioned = Get-AppxProvisionedPackage -Online -ErrorAction Stop |
            Where-Object { $_.PackageName -like "$PackageIdentityName_*" } |
            Sort-Object { [Version]($_.PackageName -split '_')[1] } -Descending |
            Select-Object -First 1
        if ($Provisioned) {
            $Parts = $Provisioned.PackageName -split '_'
            $Package = [PSCustomObject]@{
                Name         = $Parts[0]
                Version      = $Parts[1]
                Architecture = $Parts[2]
            }
            Write-CMTraceLog -Message "[$NaptScriptType] Provisioned package found: $($Package.Name) (Version: $($Package.Version), Arch: $($Package.Architecture))" -Type "INFO"
            return $Package
        }

        Write-CMTraceLog -Message "[$NaptScriptType] Provisioned package not found: $PackageIdentityName" -Type "INFO"
        return $null
    } catch {
        Write-CMTraceLog -Message "[$NaptScriptType] Error querying provisioned package $PackageIdentityName : $($_.Exception.Message)" -Type "ERROR"
        return $null
    }
}
