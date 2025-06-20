from packaging import version
import subprocess

def check_from_filename(source_url: str) -> str:
    """
    Extracts the version from the filename in the source URL.
    """
    filename = source_url.split('/')[-1]
    version_str = filename.split('-')[1]  # Assuming format like 'intune-<version>.zip'
    return version_str

def check_from_folder_name(source_url: str) -> str:
    """
    Extracts the version from the folder name in the source URL.
    """
    folder_name = source_url.split('/')[-2]  # Assuming the folder is the second last part
    version_str = folder_name.split('-')[1]  # Assuming format like 'intune-<version>'
    return version_str

def check_from_metadata_after_download(msi_path: str) -> str | None:
    result = subprocess.run(
        ["msiinfo", "export", msi_path, "Property"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError("msiinfo failed to read MSI file.")

    for line in result.stdout.splitlines():
        if line.startswith("ProductVersion"):
            return line.split()[1]
    return None


def is_newer_version(current_version: str, remote_version: str) -> bool:
    """
    Tries multiple strategies to determine whether the remote version is newer.
    """
    strategies = [
        check_from_filename,
        check_from_folder_name,
        check_from_metadata_after_download
    ]
    
    for strategy in strategies:
        try:
            remote_version = strategy(source_url)
            if remote_version and remote_version != intune_version:
                return True
        except VersionCheckError:
            continue  # Try the next method

    raise VersionCheckError("Unable to determine remote version")