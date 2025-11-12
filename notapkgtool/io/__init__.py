"""Input/Output operations for NAPT.

This module provides robust file download and upload capabilities with
features like conditional requests, retry logic, atomic writes, and
integrity verification.

Modules:

download : module
    HTTP(S) file download with retries, conditional requests, and checksums.
upload : module
    File upload adapters for Intune and storage providers (planned).

Public API:

download_file : function
    Download a file from a URL with robustness and reproducibility.
NotModifiedError : exception
    Raised when a conditional request returns HTTP 304.

Example:
    from pathlib import Path
    from notapkgtool.io import download_file

    file_path, sha256, headers = download_file(
        url="https://example.com/installer.msi",
        destination_folder=Path("./downloads"),
    )
    print(f"Downloaded to {file_path} with hash {sha256}")

"""

from .download import NotModifiedError, download_file, make_session

__all__ = ["download_file", "NotModifiedError", "make_session"]
