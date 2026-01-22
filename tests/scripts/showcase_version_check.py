#!/usr/bin/env python3
"""
Showcase runner for NAPT version_check module.

What this does:
- Extracts MSI ProductVersion from the Chrome MSI you downloaded (if available).
- Exercises compare_any() and is_newer_any() across sources: msi, exe, string.
- Prints the internal sort keys (version_key_any) to help you understand ordering.

Safe to run on any OS. MSI parsing:
- Windows: uses built-in _msi if available.
- Linux/macOS: uses msitools (msiinfo) if installed.
- If no MSI backend is available, the MSI demo section is skipped with guidance.

Run:
  poetry run python scripts/run_version_check_showcase.py
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

# Adjust import path if running directly without -m and package install
try:
    from notapkgtool.versioning import version_check as vc
except ModuleNotFoundError:
    # Allow running from repo root without installing the package
    sys.path.insert(0, ".")
    from notapkgtool.versioning import version_check as vc  # type: ignore


ART_DIR = Path("artifacts")
CHROME_MSI = ART_DIR / "googlechromestandaloneenterprise64.msi"


def title(s: str) -> None:
    bar = "=" * len(s)
    print(f"\n{bar}\n{s}\n{bar}")


def subtitle(s: str) -> None:
    print(f"\n-- {s} --")


def show_key(label: str, value: str, source: str = "string") -> None:
    try:
        k = vc.version_key_any(value, source=source)  # type: ignore[arg-type]
    except Exception as err:
        print(f"{label}: {value!r}")
        print(f"  key(error): {err}")
    else:
        print(f"{label}: {value!r}")
        print(f"  key: {k}")


def describe_compare(
    remote: str, current: str | None, *, source: vc.SourceHint
) -> None:
    print()
    print(f"[describe] source={source} remote={remote!r} current={current!r}")
    show_key("remote", remote, source)
    if current is not None:
        show_key("current", current, source)
    _ = vc.is_newer_any(remote, current, source=source)


def demo_msi_section() -> None:
    title("MSI ProductVersion extraction (Chrome MSI)")
    print(f"Looking for MSI at: {CHROME_MSI}")

    if not CHROME_MSI.exists():
        print("MSI not found. Run scripts/smoke_download_chrome.py first.")
        return

    backend = None
    if sys.platform.startswith("win"):
        backend = "_msi (Windows CPython)"
    elif shutil.which("msiinfo"):
        backend = "msitools msiinfo"
    print(f"Detected backend: {backend or 'none'}")

    try:
        dv = vc.version_from_msi_product_version(CHROME_MSI)
    except NotImplementedError as err:
        print("Skipping: no MSI parsing backend available on this host.")
        print(f"Hint: {err}")
        return
    except Exception as err:
        print("Unexpected error while parsing MSI:")
        print(err)
        return

    print(f"DiscoveredVersion: version={dv.version!r}, source={dv.source}")
    # Show MSI-specific comparison rules (only first 3 parts matter)
    # Compare against a clearly older and equal baseline
    describe_compare(dv.version, "0.0.0", source="msi")
    # Equal when only first 3 components differ in the 4th position
    three_part_equal_case = dv.version.split(".")
    if len(three_part_equal_case) >= 3:
        eq_case = ".".join(three_part_equal_case[:3] + ["1"])
        describe_compare(dv.version, eq_case, source="msi")


def demo_exe_style() -> None:
    title("EXE (4-part) comparisons")
    pairs = [
        ("10.0.19041.3720", "10.0.19041.3448"),
        ("1.2.3.4", "1.2.3.4"),
        ("1.2.3.10", "1.2.3.2"),
        ("1.2.3", "1.2.3.1"),  # missing 4th is treated as lower
    ]
    for a, b in pairs:
        describe_compare(a, b, source="exe")


def demo_string_semverish() -> None:
    title("String (semverish) comparisons")
    cases = [
        ("1.2.0-rc.1", "1.2.0-rc.2"),
        ("1.2.0-rc.10", "1.2.0-rc.2"),
        ("1.2.0-beta.11", "1.2.0-rc.1"),
        ("1.2.0", "1.2.0-rc.7"),  # final > prerelease
        ("1.2.0-zzz.1", "1.2.0-rc.1"),  # unknown tag < rc
        ("1.2.0-zzz.2", "1.2.0-beta.11"),  # unknown tag > beta
        ("1.2.0", "1.2.0-post1"),  # post > base
        ("1.2.0-hotfix-2", "1.2.0"),  # post > base
        ("v1.2.3", "1.2.3"),  # same
        ("1.2rc1", "1.2"),  # prerelease vs base
        ("24.08", "24.07"),  # two-part numeric
        ("2025.9", "2025.08"),  # numeric awareness across widths
    ]
    for a, b in cases:
        describe_compare(a, b, source="string")


def main() -> int:
    title("NAPT version_check showcase")

    # Section 1: MSI ProductVersion extraction (Chrome MSI)
    demo_msi_section()

    # Section 2: EXE-style dotted-quad comparisons
    demo_exe_style()

    # Section 3: String (semverish) comparisons
    demo_string_semverish()

    print("\nAll demos complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
