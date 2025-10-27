#!/usr/bin/env python3
"""
Smoke test for notapkgtool.processors.download.download_file using Google Chrome.

Behavior
- First run: downloads the Chrome Enterprise x64 MSI to ./artifacts/.
- Persists ETag/Last-Modified to a sidecar JSON file next to the MSI.
- Second run: re-requests the same URL with conditional headers and expects HTTP 304,
  exercising NotModifiedError handling and confirming no re-download occurs.

Notes
- The Chrome Enterprise MSI URL below is a long-lived link, but vendors can change
  URLs at any time. If it ever breaks, replace `DEFAULT_URL` with a current MSI link.
- This is a script, not a unit test; it prints progress and results to stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import TypedDict

from notapkgtool.io.download import NotModifiedError, download_file

# Long-lived (but not guaranteed) Chrome Enterprise x64 MSI.
# Replace if Google changes distribution URLs.
DEFAULT_URL = (
    "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
)

ARTIFACT_DIR = Path("artifacts")


class Meta(TypedDict, total=False):
    """Sidecar metadata persisted between runs for conditional requests."""

    etag: str
    last_modified: str
    sha256: str
    filename: str


def _meta_path(final_path: Path) -> Path:
    """Return the JSON sidecar path for a downloaded file."""
    return final_path.with_suffix(final_path.suffix + ".meta.json")


def _load_meta(p: Path) -> Meta:
    """Load sidecar metadata if present, otherwise return an empty dict."""
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)  # type: ignore[return-value]
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as err:
        print(f"warn: could not parse meta at {p}: {err}", file=sys.stderr)
        return {}


def _save_meta(p: Path, meta: Meta) -> None:
    """Persist sidecar metadata as pretty JSON."""
    with p.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def main(url: str = DEFAULT_URL, out_dir: Path = ARTIFACT_DIR) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    # First run: regular download (no conditional headers yet).
    print(f"==> 1/2 downloading: {url}")
    path, sha, headers = download_file(
        url=url,
        destination_folder=out_dir,
        validate_content_type=True,
        timeout=90,
    )
    print(f"saved to: {path}")
    print(f"sha256:  {sha}")

    # Persist conditional headers for next run.
    etag = headers.get("ETag") or headers.get("Etag") or headers.get("etag") or ""
    last_modified = headers.get("Last-Modified", "")
    print(f"headers: {headers}")

    meta: Meta = {
        "etag": etag,
        "last_modified": last_modified,
        "sha256": sha,
        "filename": path.name,
    }
    mp = _meta_path(path)
    _save_meta(mp, meta)
    print(f"wrote meta: {mp}")

    # Second run: use conditional request to test 304 path.
    print("\n==> 2/2 conditional re-check (expect NotModifiedError if unchanged)")
    try:
        _path2, _sha2, _headers2 = download_file(
            url=url,
            destination_folder=out_dir,
            validate_content_type=True,
            timeout=90,
            etag=meta.get("etag") or None,
            last_modified=meta.get("last_modified") or None,
        )
        # If we get here, the server decided content changed (200 OK); show details.
        print("server reports updated content; re-downloaded successfully")
        print(f"new file: {_path2}")
        print(f"new sha256: {_sha2}")
        print(f"new headers: {_headers2}")
    except NotModifiedError:
        print("OK: remote content not modified (HTTP 304). No re-download performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
