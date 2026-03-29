# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP(S) file download for NAPT.

Downloads files to a destination folder. Retries on transient failures,
supports ETag-based conditional requests, and writes to a .part file
before renaming on success.

Behavior:
    - Retries on status codes 429, 500, 502, 503, 504 with exponential backoff
    - Sends If-None-Match when etag is provided; If-Modified-Since when
      last_modified is provided
    - Writes to a .part file and renames on success
    - Hashes content during download; validates against expected_sha256 if set
    - Reads filename from Content-Disposition (including RFC 5987 filenames),
      falling back to the URL path
    - Forces Accept-Encoding: identity to keep ETags stable across requests

DEFAULT_CHUNK (1 MiB) is the stream chunk size.

Example:
    Basic download:
        ```python
        from pathlib import Path
        from napt.download import download_file

        result = download_file(
            url="https://example.com/installer.msi",
            destination_folder=Path("./downloads/my-app"),
        )
        print(f"Downloaded to {result.file_path}")
        print(f"SHA-256: {result.sha256}")
        ```

    Conditional download (avoid re-downloading):
        ```python
        from napt.exceptions import NotModifiedError

        try:
            result = download_file(
                url="https://example.com/installer.msi",
                destination_folder=Path("./downloads/my-app"),
                etag=previous_etag,
            )
        except NotModifiedError:
            print("File unchanged, using cached version")
        ```

    Checksum validation:
        ```python
        from napt.exceptions import NetworkError

        try:
            result = download_file(
                url="https://example.com/installer.msi",
                destination_folder=Path("./downloads/my-app"),
                expected_sha256="abc123...",
            )
        except NetworkError as e:
            print(f"Checksum mismatch: {e}")
        ```

Note:
    CDNs compute representation-specific ETags, so requesting gzip vs
    identity can yield different ETags for the same content. Forcing
    Accept-Encoding: identity keeps ETags stable. Timeouts are per-request,
    not total download time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from napt import __version__
from napt.exceptions import ConfigError, NetworkError, NotModifiedError
from napt.results import DownloadResult

# Stream size per chunk (1 MiB). Tune up/down if needed.
DEFAULT_CHUNK = 1024 * 1024


def _filename_from_cd(content_disposition: str) -> str | None:
    """Extract a filename from a Content-Disposition header.

    Parses standard filenames (filename=) and RFC 5987 encoded filenames
    (filename*=). Per RFC 6266, filename*= takes precedence when both are
    present.

    Args:
        content_disposition: Value of the Content-Disposition header.

    Returns:
        Extracted filename, or None if none found.

    """
    if not content_disposition:
        return None
    parts = [s.strip() for s in content_disposition.split(";")]
    plain_name = None
    ext_name = None
    for part in parts:
        lower = part.lower()
        if lower.startswith("filename*="):
            # RFC 5987 format: charset'language'encoded-value
            value = part.split("=", 1)[1].strip()
            try:
                charset, _, encoded = value.split("'", 2)
                ext_name = unquote(encoded, encoding=charset or "utf-8")
            except ValueError:
                pass  # Malformed, skip
        elif lower.startswith("filename="):
            value = part.split("=", 1)[1].strip().strip('"')
            if value:
                plain_name = value
    return ext_name or plain_name or None


def _filename_from_url(url: str) -> str:
    """Derive a filename from the URL path.

    Args:
        url: The URL to extract the filename from.

    Returns:
        Filename from the URL path, or "download.bin" if the path is empty.

    """
    name = Path(urlparse(url).path).name
    return name or "download.bin"


def _make_session() -> requests.Session:
    """Create a requests.Session with retry/backoff defaults.

    Retries on common transient status codes, applies exponential backoff,
    and sets a User-Agent header identifying NAPT.

    Note:
        Forces Accept-Encoding: identity to request raw (uncompressed) bytes.
        CDNs compute representation-specific ETags, so requesting gzip vs
        identity can yield different ETags for the same content. Binary
        installers (MSI/EXE/MSIX/ZIP) are already compressed, so identity
        encoding has no size cost.

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
            "User-Agent": (
                f"napt/{__version__} (+https://github.com/RogerCibrian/notapkgtool)"
            ),
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
) -> DownloadResult:
    """Downloads a URL to destination_folder.

    Follows redirects and retries transient failures. Writes to a .part file
    then renames to the final filename on success. Sends conditional headers
    if etag or last_modified is provided. Validates checksum if
    expected_sha256 is set.

    Args:
        url: Source URL.
        destination_folder: Folder to save into (created if missing).
        expected_sha256: Optional known SHA-256 (hex). If provided and the
            computed hash does not match, the .part file is deleted and
            NetworkError is raised.
        validate_content_type: If True, raises ConfigError when the server
            responds with Content-Type: text/html.
        timeout: Per-request timeout in seconds.
        etag: Previous ETag for If-None-Match conditional GET.
        last_modified: Previous Last-Modified for If-Modified-Since
            conditional GET.

    Returns:
        Download result containing file path, SHA-256 hash, and HTTP response
            headers.

    Raises:
        NotModifiedError: On HTTP 304, when the server confirms the content
            has not changed since the last request.
        NetworkError: For non-2xx responses (after retries), checksum mismatch,
            or incomplete download (Content-Length mismatch).
        ConfigError: If validate_content_type is True and the server responds
            with text/html.

    """
    from napt.logging import get_global_logger

    logger = get_global_logger()
    destination_folder = Path(destination_folder)
    destination_folder.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
        logger.verbose("HTTP", f"Using conditional request with ETag: {etag}")
    elif last_modified:
        headers["If-Modified-Since"] = last_modified
        logger.verbose(
            "HTTP", f"Using conditional request with Last-Modified: {last_modified}"
        )

    logger.verbose("HTTP", f"GET {url}")

    started_at = time.time()
    with _make_session() as session:
        # Stream response so we can hash while writing.
        resp = session.get(
            url, stream=True, allow_redirects=True, timeout=timeout, headers=headers
        )

        # Log redirects.
        if len(resp.history) > 0:
            for hist in resp.history:
                logger.verbose(
                    "HTTP",
                    (
                        f"Redirect {hist.status_code} -> "
                        f"{hist.headers.get('Location', 'unknown')}"
                    ),
                )

        # Conditional request satisfied: nothing changed since last time.
        if resp.status_code == 304:
            logger.verbose("HTTP", "Response: 304 Not Modified")
            raise NotModifiedError("Remote content not modified (HTTP 304).")

        # Raise for other HTTP errors after retries.
        try:
            resp.raise_for_status()
        except requests.HTTPError as err:
            raise NetworkError(f"download failed for {url}: {err}") from err

        logger.verbose("HTTP", f"Response: {resp.status_code} {resp.reason}")

        # Content-Disposition beats URL when naming the file.
        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition", ""))
        filename = cd_name or _filename_from_url(resp.url)
        target = destination_folder / filename

        # Log response details (always, not gated on Content-Length).
        content_length = resp.headers.get("Content-Length", "unknown")
        if content_length != "unknown":
            size_mb = int(content_length) / (1024 * 1024)
            logger.verbose(
                "HTTP", f"Content-Length: {content_length} ({size_mb:.1f} MB)"
            )
        etag_value = resp.headers.get("ETag", "not provided")
        logger.verbose("HTTP", f"ETag: {etag_value}")
        cd_header = resp.headers.get("Content-Disposition", "not provided")
        logger.verbose("HTTP", f"Content-Disposition: {cd_header}")

        # Optional content-type sanity check.
        if validate_content_type:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype.lower():
                resp.close()
                raise ConfigError(f"expected binary, got content-type={ctype}")

        total_size = int(resp.headers.get("Content-Length", "0") or 0)

        tmp = target.with_suffix(target.suffix + ".part")
        logger.verbose("FILE", f"Downloading to: {tmp}")

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
                        logger.progress("DOWNLOAD", f"{pct}%")
                        last_percent = pct

        resp.close()

        digest = sha.hexdigest()
        logger.verbose("FILE", f"SHA-256: {digest} (computed during download)")

        # Detect incomplete downloads (server closed connection early).
        if total_size and downloaded != total_size:
            tmp.unlink(missing_ok=True)
            raise NetworkError(
                f"Incomplete download for {url}: "
                f"expected {total_size} bytes, received {downloaded}"
            )

        # Validate checksum before atomic rename to keep partial files out of
        # the destination on mismatch.
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            logger.verbose(
                "FILE", f"Checksum mismatch! Expected: {expected_sha256}, Got: {digest}"
            )
            tmp.unlink(missing_ok=True)
            raise NetworkError(
                f"sha256 mismatch for {filename}: got {digest}, "
                f"expected {expected_sha256}"
            )

        # Atomically commit the file.
        logger.verbose("FILE", f"Atomic rename: {tmp.name} -> {target.name}")
        tmp.replace(target)

        elapsed = time.time() - started_at
        speed_mb = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        logger.info(
            "DOWNLOAD",
            f"Complete: {target.name} ({digest[:8]}...) "
            f"in {elapsed:.1f}s at {speed_mb:.1f} MB/s",
        )

        # Hand back headers the caller may want to persist (ETag, Last-Modified).
        return DownloadResult(
            file_path=target,
            sha256=digest,
            headers=dict(resp.headers),
        )
