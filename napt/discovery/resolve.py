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

"""Turns what a strategy found into an installer on disk.

Every discovery flow ends here. A strategy produces a download URL and,
for the version-first strategies, the version it believes that URL
serves. This module downloads the file, reads the version out of it when
the installer can report one (MSI ``ProductVersion``, MSIX
``Identity.Version``), and files it under ``downloads/<id>/<version>/``.
The installer's own version is the one recorded, because it is what the
detection and requirements scripts compare against on a device; the
version a page or API reported is only the trigger that caused the
download.

Skipping Downloads:
    Each app has one sidecar file, ``downloads/<id>/.download.json``,
    recording what was last resolved: the trigger (the URL and, when the
    strategy supplied one, the version it reported), the server's
    ``ETag`` and ``Last-Modified``, and the installer's version, name,
    and hash. The next run compares its trigger against that record:

    - A version-first strategy that reports the same version as last time
        reuses the installer without a request.
    - ``url_download`` has no version to compare, so it sends the
        ``ETag`` / ``Last-Modified`` back as a conditional request and
        reuses the installer when the server answers HTTP 304.

    The sidecar is a hint, not a record. Anything wrong with it means one
    full download, never an error, and it is written only after the
    installer is in place.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from napt.download.download import download_file
from napt.exceptions import ConfigError, NetworkError, NotModifiedError
from napt.logging import get_global_logger
from napt.paths import is_safe_path_component, safe_filename
from napt.versioning.msi import extract_msi_metadata
from napt.versioning.msix import extract_msix_metadata

from .base import StrategyResult, require_usable_version

# Holding folder for a download whose version is not known yet.
_INCOMING_DIR = ".incoming"

# Per-app record of what discovery last resolved (downloads/<id>/<name>).
_SIDECAR_NAME = ".download.json"

# Installer types whose version is read from the file itself, by version
# source name.
_SELF_VERSIONED = {".msi": "msi", ".msix": "msix"}


@dataclass(frozen=True)
class _PreviousDownload:
    """The app's last resolved download, as recorded in its sidecar file."""

    url: str
    discovered_version: str | None
    etag: str | None
    last_modified: str | None
    version: str
    file_path: Path
    sha256: str


def resolve_installer(
    url: str,
    app_dir: Path,
    *,
    source: str,
    discovered_version: str | None = None,
) -> StrategyResult:
    """Resolves a strategy's finding to an installer on disk.

    Reuses the app's last download when the sidecar shows the trigger is
    unchanged (see the module description); otherwise downloads the file,
    reads its version, and files it under that version.

    Args:
        url: URL the installer is served from.
        app_dir: The app's download directory (``downloads/<id>``).
        source: Name of the strategy, recorded as the version source when
            the installer cannot report its own version.
        discovered_version: Version the strategy reported for ``url``, or
            None for ``url_download``, which learns the version from the
            file.

    Returns:
        Resolved version, its source, file path, and SHA-256 hash. The
        ``cached`` field is True when the previous download was reused.

    Raises:
        ConfigError: If the file's version cannot be used as a folder
            name, or if ``url_download`` fetched a file that cannot report
            a version.
        NetworkError: On download or version-extraction failures.

    """
    logger = get_global_logger()
    previous = _load_sidecar(app_dir)

    try:
        if discovered_version is not None:
            # The reported version is the whole trigger. The URL is not part
            # of it, because some vendor pages embed a changing token in
            # every download link.
            if previous is not None and previous.discovered_version == (
                discovered_version
            ):
                logger.info(
                    "DISCOVERY",
                    f"Version {discovered_version} already downloaded, "
                    f"using {previous.file_path}",
                )
                return _reuse(previous, url, source)
            return _download_and_file(url, app_dir, source, discovered_version)

        if (
            previous is None
            or previous.url != url
            or not (previous.etag or previous.last_modified)
        ):
            return _download_and_file(url, app_dir, source, None)
        logger.verbose("DISCOVERY", f"Previous ETag: {previous.etag}")
        logger.verbose("DISCOVERY", f"Previous Last-Modified: {previous.last_modified}")
        try:
            return _download_and_file(
                url,
                app_dir,
                source,
                None,
                etag=previous.etag,
                last_modified=previous.last_modified,
            )
        except NotModifiedError:
            logger.info(
                "DISCOVERY",
                f"File not modified (HTTP 304), using {previous.file_path}",
            )
            return _reuse(previous, url, source)
    except (NetworkError, ConfigError):
        raise
    except Exception as err:
        raise NetworkError(f"Failed to download {url}: {err}") from err


def _reuse(previous: _PreviousDownload, url: str, source: str) -> StrategyResult:
    """Builds the result for a download the sidecar showed to be current."""
    return StrategyResult(
        version=previous.version,
        version_source=_version_source(previous.file_path, source),
        file_path=previous.file_path,
        sha256=previous.sha256,
        download_url=url,
        cached=True,
    )


def _version_source(file_path: Path, source: str) -> str:
    """Names where an installer's version comes from."""
    return _SELF_VERSIONED.get(file_path.suffix.lower(), source)


def _download_and_file(
    url: str,
    app_dir: Path,
    source: str,
    discovered_version: str | None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> StrategyResult:
    """Downloads an installer, reads its version, and files it under that version.

    The version is only known once the file is on disk, so the download
    lands in ``<app_dir>/.incoming`` first and is then moved to
    ``<app_dir>/<version>/``. Installers of other versions are never
    touched, which matters for vendors that serve every release under one
    filename. The sidecar file is written last, so an interrupted run can
    leave an installer without a sidecar but never the reverse.

    Args:
        url: Download URL.
        app_dir: The app's download directory (``downloads/<id>``).
        source: Strategy name, the version source for an installer that
            cannot report its own version.
        discovered_version: Version the strategy reported, used as the
            version for such an installer; None for ``url_download``.
        etag: ETag from the previous download, for a conditional request.
        last_modified: Last-Modified from the previous download, used when
            no ETag is available.

    Returns:
        Resolved version, the file's final path, and its hash.

    Raises:
        NotModifiedError: If the server answers HTTP 304.
        NetworkError: On download or version-extraction failure.
        ConfigError: If the version cannot be used as a folder name, or
            if there is no version at all.

    """
    logger = get_global_logger()
    incoming = app_dir / _INCOMING_DIR
    # Clear leftovers from an interrupted run.
    shutil.rmtree(incoming, ignore_errors=True)
    try:
        dl = download_file(url, incoming, etag=etag, last_modified=last_modified)
        installer_version = _installer_version(dl.file_path)
        if installer_version is not None:
            version = installer_version
            if discovered_version is not None and discovered_version != version:
                logger.info(
                    "DISCOVERY",
                    f"Installer reports version {version} ({source} reported "
                    f"{discovered_version}); recording {version}",
                )
        elif discovered_version is not None:
            version = discovered_version
        else:
            raise ConfigError(
                f"Cannot read a version from {dl.file_path.name}: url_download "
                "supports MSI and MSIX installers only. For other file types "
                "use a version-first strategy (api_github, api_json, web_scrape)."
            )
        require_usable_version(version)
        final_path = app_dir / version / dl.file_path.name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        dl.file_path.replace(final_path)
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    result = StrategyResult(
        version=version,
        version_source=_version_source(final_path, source),
        file_path=final_path,
        sha256=dl.sha256,
        download_url=url,
        cached=False,
    )
    _write_sidecar(app_dir, url, discovered_version, dl.headers, result)
    return result


def _installer_version(file_path: Path) -> str | None:
    """Reads the version an installer reports about itself.

    Args:
        file_path: Path to the downloaded installer file.

    Returns:
        The MSI ``ProductVersion`` or MSIX ``Identity.Version``, or None
        for an installer type that carries no readable version.

    Raises:
        NetworkError: If metadata extraction fails.

    """
    suffix = file_path.suffix.lower()
    if suffix not in _SELF_VERSIONED:
        return None
    try:
        if suffix == ".msi":
            return extract_msi_metadata(file_path).product_version
        return extract_msix_metadata(file_path).version
    except Exception as err:
        raise NetworkError(
            f"Failed to extract the version from {file_path}: {err}"
        ) from err


def _load_sidecar(app_dir: Path) -> _PreviousDownload | None:
    """Reads the app's sidecar file when it describes an installer on disk.

    The sidecar is a disposable hint, so every problem with it means "no
    previous download" rather than an error: a missing or unreadable file,
    a field of the wrong shape, or an installer that is no longer on disk.

    Args:
        app_dir: The app's download directory (``downloads/<id>``).

    Returns:
        The previous download, or None when there is nothing to reuse.

    """
    try:
        data = json.loads((app_dir / _SIDECAR_NAME).read_text(encoding="utf-8"))
        previous = _PreviousDownload(
            url=data["url"],
            discovered_version=data["discovered_version"],
            etag=data["etag"],
            last_modified=data["last_modified"],
            version=data["version"],
            file_path=app_dir / data["version"] / data["filename"],
            sha256=data["sha256"],
        )
        usable = (
            isinstance(previous.url, str)
            and isinstance(previous.discovered_version, str | None)
            and isinstance(previous.etag, str | None)
            and isinstance(previous.last_modified, str | None)
            and isinstance(previous.sha256, str)
            and is_safe_path_component(previous.version)
            and safe_filename(data["filename"]) == data["filename"]
            and previous.file_path.is_file()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return previous if usable else None


def _write_sidecar(
    app_dir: Path,
    url: str,
    discovered_version: str | None,
    headers: dict[str, str],
    result: StrategyResult,
) -> None:
    """Records what was resolved, so the next run can tell whether it changed."""
    # Header names arrive in whatever case the server used.
    lowered = {name.lower(): value for name, value in headers.items()}
    data = {
        "url": url,
        "discovered_version": discovered_version,
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
