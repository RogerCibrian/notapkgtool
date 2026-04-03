# Retrieve installed AppX package by identity name
function Get-InstalledAppxPackage {
    param(
        [string]$PackageIdentityName
    )

    try {
        $Package = Get-AppxPackage -Name $PackageIdentityName -ErrorAction Stop
        if ($Package) {
            Write-CMTraceLog -Message "[AppX] Package found: $($Package.Name) (Version: $($Package.Version), Arch: $($Package.Architecture))" -Type "INFO"
            return $Package
        }

        Write-CMTraceLog -Message "[AppX] Package not found: $PackageIdentityName" -Type "INFO"
        return $null
    } catch {
        Write-CMTraceLog -Message "[AppX] Error querying package $PackageIdentityName : $($_.Exception.Message)" -Type "ERROR"
        return $null
    }
}
