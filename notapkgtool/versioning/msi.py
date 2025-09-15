"""
MSI ProductVersion extraction helpers for NAPT.

Pure file introspection. No network calls here.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

from .keys import DiscoveredVersion  # reuse the shared DTO


def version_from_msi_product_version(file_path: str | Path) -> DiscoveredVersion:
    """
    Extract ProductVersion from an MSI file.

    Backends:
    - Windows: CPython '_msi' extension (most reliable on Windows hosts).
    - Elsewhere: 'msiinfo' from 'msitools' if available in PATH.
    - If neither is available, raises NotImplementedError.

    Raises
    ------
    FileNotFoundError | RuntimeError | NotImplementedError
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"MSI not found: {p}")

    if sys.platform.startswith("win"):
        try:
            import _msi  # type: ignore

            db = _msi.OpenDatabase(str(p), 0)  # 0: read-only
            view = db.OpenView(
                "SELECT `Value` FROM `Property` WHERE `Property`='ProductVersion'"
            )
            view.Execute(None)
            rec = view.Fetch()
            if rec is None:
                raise RuntimeError("ProductVersion not found in MSI Property table.")
            version = rec.GetString(1)
            if not version:
                raise RuntimeError("Empty ProductVersion in MSI Property table.")
            view.Close()
            db.Close()
            return DiscoveredVersion(
                version=version, source="msi_product_version_from_file"
            )
        except Exception as err:
            raise RuntimeError(
                f"failed to read MSI ProductVersion via _msi: {err}"
            ) from err

    msiinfo = shutil.which("msiinfo")
    if msiinfo:
        try:
            # msiinfo export <package> Property -> stdout (tab-separated)
            result = subprocess.run(
                [msiinfo, "export", str(p), "Property"],
                check=True,
                capture_output=True,
                text=True,
            )
            version: str | None = None
            for line in result.stdout.splitlines():
                parts = line.strip().split("\t", 1)  # "Property<TAB>Value"
                if len(parts) == 2 and parts[0] == "ProductVersion":
                    version = parts[1]
                    break
            if not version:
                raise RuntimeError("ProductVersion not found in MSI Property output.")
            return DiscoveredVersion(
                version=version, source="msi_product_version_from_file"
            )
        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"msiinfo failed: {err}") from err

    raise NotImplementedError(
        "MSI version extraction is not available on this host. "
        "On Windows, CPython provides '_msi'. Elsewhere, install 'msitools'."
    )
