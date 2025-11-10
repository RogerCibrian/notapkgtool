"""
PSAppDeployToolkit integration for NAPT.

This module handles PSAppDeployToolkit (PSADT) release management, caching,
and integration with NAPT's build system.

Public API:
fetch_latest_psadt_version : function
    Query GitHub API for the latest PSADT release version.
get_psadt_release : function
    Download and cache a specific PSADT release.
is_psadt_cached : function
    Check if a PSADT version is already cached locally.

Example:
    from pathlib import Path
    from notapkgtool.psadt import get_psadt_release, fetch_latest_psadt_version

    # Get latest version
    latest = fetch_latest_psadt_version()
    print(f"Latest PSADT: {latest}")

    # Download and cache
    psadt_path = get_psadt_release("latest", Path("cache/psadt"))
    print(f"PSADT cached at: {psadt_path}")
"""

from .release import (
    fetch_latest_psadt_version,
    get_psadt_release,
    is_psadt_cached,
)

__all__ = ["fetch_latest_psadt_version", "get_psadt_release", "is_psadt_cached"]
