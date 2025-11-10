"""
Robust HTTP(S) file download for NAPT.

This module provides production-grade file downloading with features designed
for reliability, reproducibility, and efficiency in automated packaging workflows.

Key Features:

- **Retry Logic with Exponential Backoff** - Automatically retries on transient failures (429, 500, 502, 503, 504) with exponential backoff. Configurable via urllib3.util.Retry.
- **Conditional Requests (HTTP 304 Not Modified)** - Supports ETag and Last-Modified headers to avoid re-downloading unchanged files.
- **Atomic Writes** - Downloads to temporary .part files with atomic rename on success to prevent partial files.
- **Integrity Verification** - SHA-256 hashing during download with optional checksum validation. Corrupted files are automatically removed.
- **Smart Filename Detection** - Respects Content-Disposition headers, falls back to URL path, handles edge cases.
- **Stable ETags** - Forces Accept-Encoding: identity to avoid representation-specific ETags and prevent false cache misses.

Exception Classes:

- NotModifiedError: Raised when conditional request returns HTTP 304 (not an error condition).

Constants:

- DEFAULT_CHUNK (int): Stream chunk size (1 MiB). Balance memory vs. progress granularity.

Example:
Basic download:

    >>> from pathlib import Path
    >>> from notapkgtool.io import download_file
    >>> path, sha256, headers = download_file(
    ...     url="https://example.com/installer.msi",
    ...     destination_folder=Path("./downloads"),
    ... )
    >>> print(f"Downloaded to {path}")
    >>> print(f"SHA-256: {sha256}")

Conditional download (avoid re-downloading):

    >>> try:
    ...     path, sha256, headers = download_file(
    ...         url="https://example.com/installer.msi",
    ...         destination_folder=Path("./downloads"),
    ...         etag=previous_etag,
    ...     )
    ... except NotModifiedError:
    ...     print("File unchanged, using cached version")

Checksum validation:

    >>> try:
    ...     path, sha256, headers = download_file(
    ...         url="https://example.com/installer.msi",
    ...         destination_folder=Path("./downloads"),
    ...         expected_sha256="abc123...",
    ...     )
    ... except ValueError as e:
    ...     print(f"Checksum mismatch: {e}")

Design Decisions:
- **Why identity encoding?** CDNs like Cloudflare compute representation-specific
  ETags. Requesting gzip vs identity yields different ETags for the same content,
  causing unnecessary re-downloads. We pin to identity for stability.

- **Why atomic writes?** Prevents partial files from appearing in the destination.
  Critical for automation where another process might start using a file before
  download completes.

- **Why stream hashing?** Computing SHA-256 while streaming avoids a second
  file read, improving I/O efficiency especially for large installers.

Notes:
- Progress output goes to stdout (can be captured/redirected)
- User-Agent identifies NAPT to help with debugging/support
- All HTTP errors are chained for better debugging
- Timeouts are per-request, not total download time
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
from pathlib import Path
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Stream size per chunk (1 MiB). Tune up/down if needed.
DEFAULT_CHUNK = 1024 * 1024


class NotModifiedError(Exception):
    """
    Raised when a conditional request (If-None-Match / If-Modified-Since)
    returns HTTP 304 Not Modified. Caller can treat this as "no work to do".
    """


def _filename_from_cd(content_disposition: str) -> str | None:
    """
    Extract a filename from a Content-Disposition header if present.

    Example header:
      'attachment; filename="setup.msi"'
    """
    if not content_disposition:
        return None
    parts = [s.strip() for s in content_disposition.split(";")]
    for part in parts:
        if part.lower().startswith("filename="):
            value = part.split("=", 1)[1].strip().strip('"')
            return value or None
    return None


def _filename_from_url(url: str) -> str:
    """
    Derive a filename from the URL path. Fallback to a generic name if empty.
    """
    name = Path(urlparse(url).path).name
    return name or "download.bin"


def _sha256_iter(chunks: Iterable[bytes]) -> str:
    """
    Compute SHA-256 from an iterator of byte chunks (stream-friendly).
    """
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


def make_session() -> requests.Session:
    """
    Create a requests.Session with sane retry/backoff defaults.

    - Retries on common transient status codes.
    - Applies exponential backoff.
    - Sets a helpful User-Agent to avoid being blocked.

    Notes on Accept-Encoding:

    - We force 'Accept-Encoding: identity' to request the raw (uncompressed) bytes.
    - Many CDNs compute representation-specific ETags (e.g., gzip vs identity).
      That can cause conditional requests (If-None-Match) to miss and trigger
      unnecessary re-downloads. Pinning identity stabilizes ETags for binary
      installers (MSI/EXE/MSIX/ZIP), which are already compressed.
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
        {
            "User-Agent": "napt/0.1 (+https://github.com/RogerCibrian/notapkgtool)",
            # Request the raw, uncompressed representation to keep ETags stable
            # across runs and avoid spurious 200s when a CDN flips to gzip.
            "Accept-Encoding": "identity",
        }
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def download_file(
    url: str,
    destination_folder: Path,
    *,
    expected_sha256: str | None = None,
    validate_content_type: bool = False,
    timeout: int = 60,
    etag: str | None = None,
    last_modified: str | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> tuple[Path, str, dict]:
    """Download a URL to destination_folder with robustness and reproducibility.

    Follows redirects and retries transient failures. Writes to <filename>.part
    then renames to <filename> on success (atomic). Sends conditional headers
    if etag/last_modified provided. Validates checksum if expected_sha256 is set.

    Args:
        url: Source URL.
        destination_folder: Folder to save into (created if missing).
        expected_sha256: Optional known SHA-256 (hex). If set and mismatched,
            raises ValueError.
        validate_content_type: If True, rejects responses with text/html content-type.
        timeout: Per-request timeout (seconds).
        etag: Previous ETag to use for If-None-Match (conditional GET).
        last_modified: Previous Last-Modified to use for If-Modified-Since (conditional GET).
        verbose: Print verbose progress.
        debug: Print debug information.

    Returns:
        A tuple (file_path, sha256_hex, headers_dict), where file_path is
            the Path to the downloaded file, sha256_hex is the SHA-256 hash
            of the file, and headers_dict contains HTTP response headers.

    Raises:
        NotModifiedError: On HTTP 304 (conditional request satisfied).
        requests.HTTPError: For non-2xx responses (after retries).
        ValueError: For content-type mismatch or checksum mismatch.
    """
    from notapkgtool.cli import print_verbose

    destination_folder = Path(destination_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
        print_verbose("HTTP", f"Using conditional request with ETag: {etag}")
    elif last_modified:
        headers["If-Modified-Since"] = last_modified
        print_verbose(
            "HTTP", f"Using conditional request with Last-Modified: {last_modified}"
        )

    print_verbose("HTTP", f"GET {url}")
    if verbose:
        print_verbose(
            "HTTP",
            "Request headers: Accept-Encoding: identity, User-Agent: napt/0.1.0",
        )

    with make_session() as session:
        # Stream response so we can hash while writing.
        resp = session.get(
            url, stream=True, allow_redirects=True, timeout=timeout, headers=headers
        )

        # Log redirects
        if verbose and len(resp.history) > 0:
            for hist in resp.history:
                print_verbose(
                    "HTTP",
                    f"Redirect {hist.status_code} -> {hist.headers.get('Location', 'unknown')}",
                )

        # Conditional request satisfied: nothing changed since last time.
        if resp.status_code == 304:
            print_verbose("HTTP", "Response: 304 Not Modified")
            resp.close()
            raise NotModifiedError("Remote content not modified (HTTP 304).")

        # Raise for other HTTP errors after retries.
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            # Chain for better context.
            raise requests.HTTPError(f"download failed for {url}: {err}") from err

        print_verbose("HTTP", f"Response: {resp.status_code} {resp.reason}")

        # Content-Disposition beats URL when naming the file.
        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition", ""))
        filename = cd_name or _filename_from_url(resp.url)
        target = destination_folder / filename

        # Log response details
        if verbose:
            content_length = resp.headers.get("Content-Length", "unknown")
            if content_length != "unknown":
                size_mb = int(content_length) / (1024 * 1024)
                print_verbose(
                    "HTTP", f"Content-Length: {content_length} ({size_mb:.1f} MB)"
                )
            etag_value = resp.headers.get("ETag", "not provided")
            print_verbose("HTTP", f"ETag: {etag_value}")
            cd_header = resp.headers.get("Content-Disposition", "not provided")
            print_verbose("HTTP", f"Content-Disposition: {cd_header}")

        # Optional content-type sanity check.
        if validate_content_type:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype.lower():
                resp.close()
                raise ValueError(f"expected binary, got content-type={ctype}")

        total_size = int(resp.headers.get("Content-Length", "0") or 0)

        tmp = target.with_suffix(target.suffix + ".part")
        print_verbose("FILE", f"Downloading to: {tmp}")

        sha = hashlib.sha256()
        downloaded = 0
        last_percent = -1
        started_at = time.time()

        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=DEFAULT_CHUNK):
                if not chunk:
                    continue
                f.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)

                # Optional lightweight progress indicator.
                if total_size:
                    pct = int(downloaded * 100 / total_size)
                    if pct != last_percent:
                        print(f"download progress: {pct}%", end="\r")
                        last_percent = pct

        # Cleanup response socket.
        resp.close()

        digest = sha.hexdigest()
        print_verbose("FILE", f"SHA-256: {digest} (computed during download)")

        # Atomically "commit" the file.
        print_verbose("FILE", f"Atomic rename: {tmp.name} -> {target.name}")
        tmp.replace(target)

        # Validate checksum if the caller expects a specific digest.
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            print_verbose(
                "FILE", f"Checksum mismatch! Expected: {expected_sha256}, Got: {digest}"
            )
            try:
                target.unlink()
            except OSError:
                pass
            raise ValueError(
                f"sha256 mismatch for {filename}: got {digest}, expected {expected_sha256}"
            )

        elapsed = time.time() - started_at
        if not verbose:
            # For non-verbose mode, just show simple completion message
            print(f"\ndownload complete: {target} ({digest}) in {elapsed:.1f}s")
        else:
            # For verbose mode, show detailed file info
            print_verbose("FILE", f"Download complete: {target}")
            print_verbose("FILE", f"Time elapsed: {elapsed:.1f}s")

        # Hand back headers the caller may want to persist (ETag, Last-Modified).
        return target, digest, dict(resp.headers)
