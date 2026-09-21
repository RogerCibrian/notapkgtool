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

"""url_download discovery flow.

This module is intentionally not a
[DiscoveryStrategy][napt.discovery.base.DiscoveryStrategy]. The
strategies in [napt.discovery.base][] produce a
[RemoteVersion][napt.discovery.base.RemoteVersion] from configuration
alone (version-first). ``url_download`` cannot do that: it has no
remote endpoint to query for the version, so it must download the
installer and extract the version from the file's metadata. The
discovery orchestrator special-cases ``strategy: url_download`` and
dispatches to
[run_url_download][napt.discovery.url_download.run_url_download] directly.

Conditional Requests:
    Each download writes ``downloads/<id>/.download.json`` beside the
    app's version folders. It records what the URL served (``ETag``,
    ``Last-Modified``) and where that installer was filed. The next run
    sends those values as ``If-None-Match`` / ``If-Modified-Since``, and a
    server response of HTTP 304 reuses the installer without a
    re-download. The values are sent only while the installer they
    describe is still on disk, so a 304 can always be honored. The file
    is disposable: a missing or unreadable one costs one full download.

Supported File Types:
    - ``.msi``: version is read from the MSI ProductVersion property.
    - Other extensions raise [ConfigError][napt.exceptions.ConfigError].
        For non-MSI installers, use a version-first strategy.

Recipe Example:
    ```yaml
    discovery:
      strategy: url_download
      url: "https://vendor.example.com/installer.msi"
    ```

"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Any

from napt.download.download import download_file
from napt.exceptions import ConfigError, NetworkError, NotModifiedError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component, safe_filename
from napt.versioning.msi import extract_msi_metadata

from .base import StrategyResult, require_usable_version

# Holding folder for a download whose version is not known yet.
_INCOMING_DIR = ".incoming"

# Per-app record of what the URL served last time (downloads/<id>/<name>).
_SIDECAR_NAME = ".download.json"


@dataclass(frozen=True)
class _PreviousDownload:
    """The last download of an app's URL, as recorded in its sidecar file."""

    etag: str | None
    last_modified: str | None
    version: str
    file_path: Path
    sha256: str


def run_url_download(
    app_config: dict[str, Any],
    output_dir: Path,
) -> StrategyResult:
    """Downloads a fixed URL and extracts the version from the resulting file.

    Issues a conditional HTTP request when the app's sidecar file records
    an ``ETag`` or ``Last-Modified`` for an installer that is still on
    disk. On HTTP 304 that installer is reused; otherwise the fresh
    download is filed under the version read from it (MSI ProductVersion
    today).

    Args:
        app_config: Merged recipe configuration dict containing
            ``discovery.url`` and ``id``.
        output_dir: Base directory to download into. The file lands
            in ``output_dir / app_id / version``.

    Returns:
        Resolved version, file path, and SHA-256 hash. The ``cached``
        field is True when HTTP 304 was used to reuse the previously
        downloaded file.

    Raises:
        ConfigError: If ``discovery.url`` is missing, or if the
            downloaded file is not an MSI (version extraction is
            not supported for other file types).
        NetworkError: On download or version-extraction failures.

    """
    logger = get_global_logger()
    source = app_config.get("discovery", {})
    url = source.get("url")
    if not url:
        raise ConfigError("url_download strategy requires 'discovery.url' in config")

    app_dir = output_dir / app_config["id"]

    logger.verbose("DISCOVERY", "Strategy: url_download (file-first)")
    logger.verbose("DISCOVERY", f"Source URL: {url}")

    previous = _load_sidecar(app_dir, url)
    if previous:
        logger.verbose("DISCOVERY", f"Previous ETag: {previous.etag}")
        logger.verbose("DISCOVERY", f"Previous Last-Modified: {previous.last_modified}")

    try:
        if previous is None:
            return _download_into_version_folder(url, app_dir)
        try:
            return _download_into_version_folder(
                url,
                app_dir,
                etag=previous.etag,
                last_modified=previous.last_modified,
            )
        except NotModifiedError:
            logger.info(
                "DISCOVERY",
                f"File not modified (HTTP 304), using {previous.file_path}",
            )
            return StrategyResult(
                version=previous.version,
                version_source="url_download",
                file_path=previous.file_path,
                sha256=previous.sha256,
                download_url=url,
                cached=True,
            )
    except (NetworkError, ConfigError):
        raise
    except Exception as err:
        raise NetworkError(f"Failed to download {url}: {err}") from err


def validate_url_download_config(app_config: dict[str, Any]) -> list[str]:
    """Validates url_download configuration fields.

    Called by [napt.validation.validate_config][] to compose the
    url_download field rules into the overall recipe validation.

    Args:
        app_config: Merged recipe configuration dict.

    Returns:
        Human-readable error messages. Empty when configuration is valid.

    """
    errors: list[str] = []
    source = app_config.get("discovery", {})

    if "url" not in source:
        errors.append("Missing required field: discovery.url")
    elif not isinstance(source["url"], str):
        errors.append("discovery.url must be a string")
    elif not source["url"].strip():
        errors.append("discovery.url cannot be empty")

    return errors


def _load_sidecar(app_dir: Path, url: str) -> _PreviousDownload | None:
    """Reads the app's sidecar file when it can support a conditional request.

    The sidecar is a disposable hint, so every problem with it means "no
    previous download" rather than an error: a missing or unreadable file,
    a record for a different URL, no ``ETag`` or ``Last-Modified``, or an
    installer that is no longer on disk.

    Args:
        app_dir: The app's download directory (``downloads/<id>``).
        url: The recipe's download URL.

    Returns:
        The previous download, or None when a conditional request cannot
        be made or could not be honored.

    """
    try:
        data = json.loads((app_dir / _SIDECAR_NAME).read_text(encoding="utf-8"))
        previous = _PreviousDownload(
            etag=data["etag"],
            last_modified=data["last_modified"],
            version=data["version"],
            file_path=app_dir / data["version"] / data["filename"],
            sha256=data["sha256"],
        )
        usable = (
            data["url"] == url
            and isinstance(previous.etag, str | None)
            and isinstance(previous.last_modified, str | None)
            and isinstance(previous.sha256, str)
            and bool(previous.etag or previous.last_modified)
            and is_safe_path_component(previous.version)
            and safe_filename(data["filename"]) == data["filename"]
            and previous.file_path.is_file()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return previous if usable else None


def _write_sidecar(
    app_dir: Path, url: str, headers: dict[str, str], result: StrategyResult
) -> None:
    """Records what the URL served, for the next run's conditional request."""
    # Header names arrive in whatever case the server used.
    lowered = {name.lower(): value for name, value in headers.items()}
    data = {
        "url": url,
        "etag": lowered.get("etag"),
        "last_modified": lowered.get("last-modified"),
        "version": result.version,
        "filename": result.file_path.name,
        "sha256": result.sha256,
    }
    try:
        (app_dir / _SIDECAR_NAME).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as err:
        get_global_logger().warning(
            "DISCOVERY",
            f"Could not write {app_dir / _SIDECAR_NAME}: {err}. "
            "The next run will download the full file.",
        )


def _download_into_version_folder(
    url: str,
    app_dir: Path,
    etag: str | None = None,
    last_modified: str | None = None,
) -> StrategyResult:
    """Downloads an installer and files it under its version.

    The version is only known once the file is on disk, so the download
    lands in ``<app_dir>/.incoming`` first and is then moved to
    ``<app_dir>/<version>/``. Installers of other versions are never
    touched, which matters for vendors that serve every release under one
    filename. The sidecar file is written last, so an interrupted run can
    leave an installer without a sidecar but never the reverse.

    Args:
        url: Download URL.
        app_dir: The app's download directory (``downloads/<id>``).
        etag: ETag from the previous download, for a conditional request.
        last_modified: Last-Modified from the previous download, used when
            no ETag is available.

    Returns:
        Resolved version, the file's final path, and download metadata.

    Raises:
        NotModifiedError: If the server answers HTTP 304.
        NetworkError: On download or version-extraction failure.
        ConfigError: If the file is not an MSI, or its version cannot be
            used as a folder name.

    """
    incoming = app_dir / _INCOMING_DIR
    # Clear leftovers from an interrupted run.
    shutil.rmtree(incoming, ignore_errors=True)
    try:
        dl = download_file(url, incoming, etag=etag, last_modified=last_modified)
        version = _extract_version(dl.file_path)
        require_usable_version(version)
        final_path = app_dir / version / dl.file_path.name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        dl.file_path.replace(final_path)
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    result = StrategyResult(
        version=version,
        version_source="url_download",
        file_path=final_path,
        sha256=dl.sha256,
        download_url=url,
        cached=False,
    )
    _write_sidecar(app_dir, url, dl.headers, result)
    return result


def _extract_version(file_path: Path) -> str:
    """Extracts a version string from an installer file's metadata.

    Currently supports MSI files via
    [extract_msi_metadata][napt.versioning.msi.extract_msi_metadata].
    Other file types raise [ConfigError][napt.exceptions.ConfigError] —
    use a version-first strategy for those instead.

    Args:
        file_path: Path to the downloaded installer file.

    Returns:
        Version string from the file's metadata.

    Raises:
        ConfigError: If ``file_path`` is not an MSI installer.
        NetworkError: If MSI metadata extraction fails.

    """
    if file_path.suffix.lower() != ".msi":
        raise ConfigError(
            f"Cannot extract version from file type: {file_path.suffix!r}. "
            f"url_download strategy currently supports MSI files only. "
            f"For other file types, use a version-first strategy "
            f"(api_github, api_json, web_scrape) or ensure the file "
            f"is an MSI installer."
        )

    try:
        return extract_msi_metadata(file_path).product_version
    except Exception as err:
        raise NetworkError(
            f"Failed to extract MSI ProductVersion from {file_path}: {err}"
        ) from err
