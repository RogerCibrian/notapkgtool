"""
Download processor for NAPT.

Responsibilities:
- Safely download files from HTTP(S) sources.
- Handle retries, redirects, and timeouts.
- Choose sensible filenames from Content-Disposition or URL.
- Write atomically (.part then rename).
- Optionally validate checksums.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry

DEFAULT_CHUNK = 1024 * 1024  # Stream download in 1 MiB chunks


def _sha256_file(p: Path) -> str:
    """
    Compute SHA256 checksum of a file.

    :param p: Path to file.
    :return: Hex digest string.
    """
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(DEFAULT_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _filename_from_cd(content_disposition: str) -> str | None:
    """
    Parse a filename from Content-Disposition header if present.

    :param content_disposition: Header value (e.g., 'attachment; filename="setup.msi"').
    :return: Filename or None if not found.
    """
    if not content_disposition:
        return None
    parts = [s.strip() for s in content_disposition.split(";")]
    for part in parts:
        if part.lower().startswith("filename="):
            return part.split("=", 1)[1].strip().strip('"')
    return None


def get_filename_from_url(url: str) -> str:
    """
    Derive a filename from the URL path.

    :param url: URL string.
    :return: Filename (falls back to 'download.bin' if empty).
    """
    name = Path(urlparse(url).path).name
    return name or "download.bin"


def make_session() -> requests.Session:
    """
    Create a requests.Session with retry/backoff logic.

    :return: Configured Session.
    """
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    s.headers.update(
        {"User-Agent": "napt/0.1 (+https://github.com/yourorg/notapkgtool)"}
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def download_file(
    url: str,
    destination_folder: Path,
    expected_sha256: str | None = None,
    validate_content_type: bool = False,
    timeout: int = 60,
) -> tuple[Path, str]:
    """
    Download a file from URL to destination_folder.

    - Creates destination folder if missing.
    - Writes atomically via .part file then renames.
    - Returns (path, sha256).
    - Optionally validates SHA256 checksum.

    :param url: File URL.
    :param destination_folder: Where to store the file.
    :param expected_sha256: Optional SHA256 hex digest to validate.
    :param validate_content_type: If True, reject text/html responses.
    :param timeout: HTTP timeout in seconds.
    :return: Tuple of (downloaded Path, sha256 digest).
    """
    destination_folder = Path(destination_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)

    with make_session() as session:
        resp = session.get(url, stream=True, allow_redirects=True, timeout=timeout)
        resp.raise_for_status()

        # Decide filename: Content-Disposition > final URL
        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition", ""))
        filename = cd_name or get_filename_from_url(resp.url)
        target = destination_folder / filename

        if validate_content_type:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype.lower():
                raise ValueError(f"expected binary, got content-type={ctype}")

        total_size = int(resp.headers.get("Content-Length", "0") or 0)

        # Write to temp file first
        tmp = target.with_suffix(target.suffix + ".part")
        sha = hashlib.sha256()
        downloaded = 0
        last_percent = -1

        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=DEFAULT_CHUNK):
                if not chunk:
                    continue
                f.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)

                if total_size:
                    pct = int(downloaded * 100 / total_size)
                    if pct != last_percent:
                        print(f"download progress: {pct}%", end="\r")
                        last_percent = pct

        tmp.replace(target)
        digest = sha.hexdigest()

        # Verify checksum if expected provided
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            target.unlink(missing_ok=True)
            raise ValueError(
                f"sha256 mismatch for {filename}: got {digest}, expected {expected_sha256}"
            )

        print(f"\ndownload complete: {target} ({digest})")
        return target, digest
