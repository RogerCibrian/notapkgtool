"""
Download processor for NAPT.

Responsibilities
- Safely download files over HTTP(S) with retries, redirects, and timeouts.
- Support conditional requests (ETag / Last-Modified) to skip unchanged downloads.
- Choose a sane filename from Content-Disposition or URL path.
- Write atomically: stream to .part and rename on success to avoid partial artifacts.
- Compute and (optionally) validate SHA-256 checksums for reproducibility.

Conventions
- Modern type hints (X | None; tuple[...] etc.).
- Organized imports: stdlib -> third-party -> first-party.
- Exceptions are chained (raise ... from err) for better tracebacks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Iterable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry

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
    *,
    expected_sha256: str | None = None,
    validate_content_type: bool = False,
    timeout: int = 60,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[Path, str, dict]:
    """
    Download a URL to destination_folder with robustness and reproducibility.

    Behavior
    - Follows redirects and retries transient failures.
    - If validate_content_type=True, rejects text/html (helps catch "download page" instead of a file).
    - Writes to <filename>.part then renames to <filename> on success (atomic).
    - Returns (final_path, sha256, response_headers_dict).
    - If 'expected_sha256' is set, validates and raises on mismatch (removes corrupt file).
    - If 'etag' and/or 'last_modified' are given, sends conditional headers. A 304 causes NotModifiedError.

    Parameters
    - url: Source URL.
    - destination_folder: Folder to save into (created if missing).
    - expected_sha256: Optional known SHA-256 (hex). If set and mismatched, raises ValueError.
    - validate_content_type: If True, rejects responses with text/html content-type.
    - timeout: Per-request timeout (seconds).
    - etag: Previous ETag to use for If-None-Match (conditional GET).
    - last_modified: Previous Last-Modified to use for If-Modified-Since (conditional GET).

    Returns
    - (Path, sha256_hex, headers_dict)

    Raises
    - NotModifiedError on HTTP 304 (conditional request satisfied).
    - requests.HTTPError for non-2xx (after retries).
    - ValueError for content-type mismatch or checksum mismatch.
    """
    destination_folder = Path(destination_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    with make_session() as session:
        # Stream response so we can hash while writing.
        resp = session.get(
            url, stream=True, allow_redirects=True, timeout=timeout, headers=headers
        )

        # Conditional request satisfied: nothing changed since last time.
        if resp.status_code == 304:
            resp.close()
            raise NotModifiedError("Remote content not modified (HTTP 304).")

        # Raise for other HTTP errors after retries.
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            # Chain for better context.
            raise requests.HTTPError(f"download failed for {url}: {err}") from err

        # Content-Disposition beats URL when naming the file.
        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition", ""))
        filename = cd_name or _filename_from_url(resp.url)
        target = destination_folder / filename

        # Optional content-type sanity check.
        if validate_content_type:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype.lower():
                resp.close()
                raise ValueError(f"expected binary, got content-type={ctype}")

        total_size = int(resp.headers.get("Content-Length", "0") or 0)

        tmp = target.with_suffix(target.suffix + ".part")
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

        # Atomically "commit" the file.
        tmp.replace(target)

        digest = sha.hexdigest()

        # Validate checksum if the caller expects a specific digest.
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            try:
                target.unlink()
            except OSError:
                pass
            raise ValueError(
                f"sha256 mismatch for {filename}: got {digest}, expected {expected_sha256}"
            )

        elapsed = time.time() - started_at
        print(f"\ndownload complete: {target} ({digest}) in {elapsed:.1f}s")

        # Hand back headers the caller may want to persist (ETag, Last-Modified).
        return target, digest, dict(resp.headers)
