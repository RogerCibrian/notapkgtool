"""
Tests for napt.versioning module.

Tests version comparison and extraction including:
- Semantic versioning comparison
- Numeric version comparison (MSI)
- Lexicographic fallback
- Prerelease tag ordering
- Version key generation
- MSI architecture detection from Template
"""

from __future__ import annotations

import pytest

from napt.exceptions import ConfigError
from napt.versioning import compare, is_newer, version_key
from napt.versioning.msi import _architecture_from_template


class TestVersionComparison:
    """Tests for version comparison functions."""

    def test_semver_basic_comparison(self):
        """Tests that basic semantic version ordering is correct."""
        assert compare("1.2.0", "1.1.9") == 1  # newer
        assert compare("1.1.9", "1.2.0") == -1  # older
        assert compare("1.2.0", "1.2.0") == 0  # equal

    def test_semver_major_minor_patch(self):
        """Tests that major.minor.patch version ordering is correct."""
        assert compare("2.0.0", "1.9.9") == 1  # major bump
        assert compare("1.10.0", "1.9.0") == 1  # minor bump
        assert compare("1.0.10", "1.0.9") == 1  # patch bump

    def test_semver_prerelease_ordering(self):
        """Tests that prerelease versions sort below their release."""
        # Release > prerelease
        assert compare("1.0.0", "1.0.0-rc.1") == 1
        assert compare("1.0.0-rc.1", "1.0.0") == -1

        # Prerelease tag ordering: alpha < beta < rc
        assert compare("1.0.0-beta", "1.0.0-alpha") == 1
        assert compare("1.0.0-rc", "1.0.0-beta") == 1
        assert compare("1.0.0-rc.2", "1.0.0-rc.1") == 1

    def test_semver_with_v_prefix(self):
        """Tests that the 'v' prefix is normalized correctly."""
        assert compare("v1.2.0", "v1.1.9") == 1
        assert compare("v1.2.0", "1.2.0") == 0  # v prefix ignored

    def test_lexicographic_comparison(self):
        """Tests lexicographic (string) comparison for non-version strings."""
        # For build IDs, timestamps, etc.
        assert compare("build-2025-01-02", "build-2025-01-01") == 1
        assert compare("b", "a") == 1
        assert compare("1.0", "9.0") == -1  # lexicographic, not numeric


class TestIsNewer:
    """Tests for is_newer function."""

    def test_is_newer_true(self):
        """Tests that newer versions return True."""
        assert is_newer("1.2.0", "1.1.9")
        assert is_newer("2.0.0", "1.9.9")

    def test_is_newer_false(self):
        """Tests that older versions return False."""
        assert not is_newer("1.1.9", "1.2.0")
        assert not is_newer("1.0.0-rc.1", "1.0.0")

    def test_is_newer_equal(self):
        """Tests that equal versions return False."""
        assert not is_newer("1.2.0", "1.2.0")

    def test_is_newer_no_current(self):
        """Tests that any version is newer than None."""
        assert is_newer("1.0.0", None)
        assert is_newer("0.0.1", None)

class TestVersionKey:
    """Tests for version_key function."""

    def test_version_keys_sortable(self):
        """Tests that version keys can be used for sorting."""
        versions = ["1.0.0", "1.2.0", "1.1.0", "2.0.0"]
        sorted_versions = sorted(versions, key=lambda v: version_key(v))
        assert sorted_versions == ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]

    def test_version_keys_with_prerelease(self):
        """Tests that prerelease versions sort correctly."""
        versions = ["1.0.0", "1.0.0-rc.1", "1.0.0-beta", "1.0.0-alpha"]
        sorted_versions = sorted(versions, key=lambda v: version_key(v))
        expected = ["1.0.0-alpha", "1.0.0-beta", "1.0.0-rc.1", "1.0.0"]
        assert sorted_versions == expected

class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_version_strings(self):
        """Tests that empty version strings are handled without crashing."""
        result = compare("", "1.0.0")
        assert isinstance(result, int)

    def test_very_long_version_numbers(self):
        """Tests that versions with many parts compare correctly."""
        v1 = "1.2.3.4.5.6.7.8"
        v2 = "1.2.3.4.5.6.7.9"
        assert compare(v1, v2) == -1

    def test_mixed_format_versions(self):
        """Tests that format differences are normalized correctly."""
        # v prefix is normalized
        assert compare("v1.2.3", "1.2.3") == 0
        # "final" is not a recognized post-release tag, so it's a prerelease
        # Therefore 1.2.3-final < 1.2.3 (prerelease < release)
        assert compare("1.2.3-final", "1.2.3") < 0

    def test_chrome_style_versions(self):
        """Tests real-world Chrome-style 4-part versions."""
        assert compare("141.0.7390.123", "140.0.7339.128") == 1
        assert compare("141.0.7390.123", "141.0.7390.122") == 1


class TestArchitectureFromTemplate:
    """Tests for MSI Template architecture parsing."""

    def test_x64_template(self):
        """Tests x64 template parsing."""
        assert _architecture_from_template("x64;1033") == "x64"
        assert _architecture_from_template("X64;1033") == "x64"  # Case insensitive

    def test_intel_template_maps_to_x86(self):
        """Tests that Intel template maps to x86."""
        assert _architecture_from_template("Intel;1033") == "x86"
        assert _architecture_from_template("INTEL;1033") == "x86"

    def test_arm64_template(self):
        """Tests ARM64 template parsing."""
        assert _architecture_from_template("Arm64;1033") == "arm64"
        assert _architecture_from_template("ARM64;1033,2046") == "arm64"

    def test_amd64_alias_maps_to_x64(self):
        """Tests that the AMD64 unofficial alias maps to x64."""
        assert _architecture_from_template("AMD64;1033") == "x64"
        assert _architecture_from_template("amd64;1033") == "x64"

    def test_empty_platform_defaults_to_x86(self):
        """Tests that an empty platform defaults to x86 per MS docs."""
        assert _architecture_from_template(";1033") == "x86"
        assert _architecture_from_template("  ;1033") == "x86"

    def test_discards_language_codes(self):
        """Tests that language codes after the semicolon are discarded."""
        assert _architecture_from_template("x64;1033") == "x64"
        assert _architecture_from_template("x64;1033,2046") == "x64"
        assert _architecture_from_template("x64;1041,1033") == "x64"

    def test_intel64_raises_config_error(self):
        """Tests that Intel64 (Itanium) raises ConfigError."""
        with pytest.raises(ConfigError, match="Itanium"):
            _architecture_from_template("Intel64;1033")

    def test_arm32_raises_config_error(self):
        """Tests that Arm (Windows RT 32-bit) raises ConfigError."""
        with pytest.raises(ConfigError, match="Windows RT"):
            _architecture_from_template("Arm;1033")

    def test_unknown_platform_raises_config_error(self):
        """Tests that an unknown platform raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown"):
            _architecture_from_template("mips;1033")

    def test_template_without_semicolon(self):
        """Tests that a template without a semicolon is handled."""
        assert _architecture_from_template("x64") == "x64"
        assert _architecture_from_template("Intel") == "x86"

    def test_whitespace_handling(self):
        """Tests that whitespace in the template is handled."""
        assert _architecture_from_template("  x64  ;1033") == "x64"
        assert _architecture_from_template("x64 ; 1033") == "x64"
