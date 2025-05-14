from packaging import version

def is_newer_version(remote_version: str, current_version: str) -> bool:
    """
    Compare two version strings and return True if the remote version is newer.
    """
    return version.parse(remote_version) > version.parse(current_version)