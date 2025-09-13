import pytest

import notapkgtool.processors.version_check as vc


def test_is_newer_semver_true():
    assert vc.is_newer("1.2.0", "1.1.9", "semver")
    assert vc.is_newer("2.0.0", None, "semver")  # no current -> newer


def test_is_newer_semver_prerelease_ordering():
    # 1.2.0 > 1.2.0-rc.1
    assert vc.is_newer("1.2.0", "1.2.0-rc.1", "semver")
    # fallback to lexicographic for non-semver strings
    assert vc.is_newer("build-2025-09-01", "build-2025-08-30", "semver")


def test_is_newer_lexicographic():
    assert vc.is_newer("b", "a", "lexicographic")
    assert not vc.is_newer("1.0", "9.0", "lexicographic")


def test_version_from_regex_in_url_named_group():
    dv = vc.version_from_regex_in_url(
        "https://vendor.com/app-24.08-x64.exe",
        r"app-(?P<version>\d+\.\d+)-x64\.exe",
    )
    assert dv.version == "24.08"
    assert dv.source == "regex_in_url"


def test_version_from_regex_in_url_no_match_raises():
    with pytest.raises(ValueError):
        vc.version_from_regex_in_url(
            "https://vendor.com/app.exe",
            r"app-(?P<version>\d+\.\d+)-x64\.exe",
        )
