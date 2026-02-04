"""
Tests for napt.versioning module.

Tests version comparison and extraction including:
- Semantic versioning comparison
- Numeric version comparison (MSI/EXE)
- Lexicographic fallback
- Prerelease tag ordering
- Version key generation
- MSI architecture detection from Template
"""

from __future__ import annotations

import pytest

from napt.exceptions import ConfigError
from napt.versioning import (
    DiscoveredVersion,
    architecture_from_template,
    compare_any,
    is_newer_any,
    version_key_any,
)


class TestVersionComparison:
    """Tests for version comparison functions."""

    def test_semver_basic_comparison(self):
        """Test basic semantic version comparison."""
        assert compare_any("1.2.0", "1.1.9") == 1  # newer
        assert compare_any("1.1.9", "1.2.0") == -1  # older
        assert compare_any("1.2.0", "1.2.0") == 0  # equal

    def test_semver_major_minor_patch(self):
        """Test major.minor.patch version ordering."""
        assert compare_any("2.0.0", "1.9.9") == 1  # major bump
        assert compare_any("1.10.0", "1.9.0") == 1  # minor bump
        assert compare_any("1.0.10", "1.0.9") == 1  # patch bump

    def test_semver_prerelease_ordering(self):
        """Test prerelease version ordering."""
        # Release > prerelease
        assert compare_any("1.0.0", "1.0.0-rc.1") == 1
        assert compare_any("1.0.0-rc.1", "1.0.0") == -1

        # Prerelease tag ordering: alpha < beta < rc
        assert compare_any("1.0.0-beta", "1.0.0-alpha") == 1
        assert compare_any("1.0.0-rc", "1.0.0-beta") == 1
        assert compare_any("1.0.0-rc.2", "1.0.0-rc.1") == 1

    def test_semver_with_v_prefix(self):
        """Test that 'v' prefix is handled correctly."""
        assert compare_any("v1.2.0", "v1.1.9") == 1
        assert compare_any("v1.2.0", "1.2.0") == 0  # v prefix ignored

    def test_msi_numeric_comparison(self):
        """Test MSI 3-part numeric version comparison."""
        assert compare_any("1.2.3", "1.2.2", source="msi") == 1
        assert compare_any("2.0.0", "1.9.9", source="msi") == 1
        assert compare_any("1.2.3", "1.2.3", source="msi") == 0

    def test_exe_numeric_comparison(self):
        """Test EXE 4-part numeric version comparison."""
        assert compare_any("1.2.3.4", "1.2.3.3", source="exe") == 1
        assert compare_any("1.2.3.10", "1.2.3.9", source="exe") == 1
        assert compare_any("1.0.0.0", "1.0.0.0", source="exe") == 0

    def test_lexicographic_comparison(self):
        """Test lexicographic (string) comparison."""
        # For build IDs, timestamps, etc.
        assert compare_any("build-2025-01-02", "build-2025-01-01") == 1
        assert compare_any("b", "a") == 1
        assert compare_any("1.0", "9.0") == -1  # lexicographic, not numeric


class TestIsNewerAny:
    """Tests for is_newer_any function."""

    def test_is_newer_true(self):
        """Test that newer versions return True."""
        assert is_newer_any("1.2.0", "1.1.9")
        assert is_newer_any("2.0.0", "1.9.9")

    def test_is_newer_false(self):
        """Test that older versions return False."""
        assert not is_newer_any("1.1.9", "1.2.0")
        assert not is_newer_any("1.0.0-rc.1", "1.0.0")

    def test_is_newer_equal(self):
        """Test that equal versions return False."""
        assert not is_newer_any("1.2.0", "1.2.0")

    def test_is_newer_no_current(self):
        """Test that any version is newer than None."""
        assert is_newer_any("1.0.0", None)
        assert is_newer_any("0.0.1", None)

    def test_is_newer_with_source_hint(self):
        """Test is_newer with different source hints."""
        assert is_newer_any("1.2.3", "1.2.2", source="msi")
        assert is_newer_any("1.2.3.4", "1.2.3.3", source="exe")


class TestVersionKeyAny:
    """Tests for version_key_any function."""

    def test_version_keys_sortable(self):
        """Test that version keys can be used for sorting."""
        versions = ["1.0.0", "1.2.0", "1.1.0", "2.0.0"]
        sorted_versions = sorted(versions, key=lambda v: version_key_any(v))
        assert sorted_versions == ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]

    def test_version_keys_with_prerelease(self):
        """Test that prerelease versions sort correctly."""
        versions = ["1.0.0", "1.0.0-rc.1", "1.0.0-beta", "1.0.0-alpha"]
        sorted_versions = sorted(versions, key=lambda v: version_key_any(v))
        expected = ["1.0.0-alpha", "1.0.0-beta", "1.0.0-rc.1", "1.0.0"]
        assert sorted_versions == expected

    def test_msi_version_keys(self):
        """Test that MSI version keys work correctly."""
        v1 = version_key_any("1.2.3", source="msi")
        v2 = version_key_any("1.2.4", source="msi")
        assert v1 < v2


class TestDiscoveredVersion:
    """Tests for DiscoveredVersion dataclass."""

    def test_discovered_version_creation(self):
        """Test creating DiscoveredVersion instances."""
        dv = DiscoveredVersion(version="1.2.3", source="test")
        assert dv.version == "1.2.3"
        assert dv.source == "test"

    def test_discovered_version_immutable(self):
        """Test that DiscoveredVersion is immutable (frozen)."""
        dv = DiscoveredVersion(version="1.2.3", source="test")
        with pytest.raises(AttributeError):
            dv.version = "1.2.4"  # type: ignore


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_version_strings(self):
        """Test handling of empty version strings."""
        # Empty strings should be handled without crashing
        # Lexicographic comparison: "" < "1.0.0"
        result = compare_any("", "1.0.0")
        # Result may vary, just ensure it doesn't crash
        assert isinstance(result, int)

    def test_very_long_version_numbers(self):
        """Test handling of version with many parts."""
        v1 = "1.2.3.4.5.6.7.8"
        v2 = "1.2.3.4.5.6.7.9"
        assert compare_any(v1, v2) == -1

    def test_mixed_format_versions(self):
        """Test comparing versions with different formats."""
        # Should handle gracefully - v prefix is normalized
        assert compare_any("v1.2.3", "1.2.3") == 0
        # "final" is not a recognized post-release tag, so it's a prerelease
        # Therefore 1.2.3-final < 1.2.3 (prerelease < release)
        assert compare_any("1.2.3-final", "1.2.3") < 0

    def test_chrome_style_versions(self):
        """Test real-world Chrome-style versions."""
        assert compare_any("141.0.7390.123", "140.0.7339.128") == 1
        assert compare_any("141.0.7390.123", "141.0.7390.122") == 1


class TestArchitectureFromTemplate:
    """Tests for MSI Template architecture parsing."""

    def test_x64_template(self):
        """Test x64 template parsing."""
        assert architecture_from_template("x64;1033") == "x64"
        assert architecture_from_template("X64;1033") == "x64"  # Case insensitive

    def test_intel_template_maps_to_x86(self):
        """Test Intel template maps to x86."""
        assert architecture_from_template("Intel;1033") == "x86"
        assert architecture_from_template("INTEL;1033") == "x86"

    def test_arm64_template(self):
        """Test ARM64 template parsing."""
        assert architecture_from_template("Arm64;1033") == "arm64"
        assert architecture_from_template("ARM64;1033,2046") == "arm64"

    def test_amd64_alias_maps_to_x64(self):
        """Test AMD64 unofficial alias maps to x64."""
        assert architecture_from_template("AMD64;1033") == "x64"
        assert architecture_from_template("amd64;1033") == "x64"

    def test_empty_platform_defaults_to_x86(self):
        """Test empty platform defaults to x86 (Intel) per MS docs."""
        assert architecture_from_template(";1033") == "x86"
        assert architecture_from_template("  ;1033") == "x86"

    def test_discards_language_codes(self):
        """Test that language codes after semicolon are discarded."""
        # All should return x64 regardless of language codes
        assert architecture_from_template("x64;1033") == "x64"
        assert architecture_from_template("x64;1033,2046") == "x64"
        assert architecture_from_template("x64;1041,1033") == "x64"

    def test_intel64_raises_config_error(self):
        """Test Intel64 (Itanium) raises ConfigError."""
        with pytest.raises(ConfigError, match="Itanium"):
            architecture_from_template("Intel64;1033")

    def test_arm32_raises_config_error(self):
        """Test Arm (Windows RT 32-bit) raises ConfigError."""
        with pytest.raises(ConfigError, match="Windows RT"):
            architecture_from_template("Arm;1033")

    def test_unknown_platform_raises_config_error(self):
        """Test unknown platform raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown"):
            architecture_from_template("mips;1033")

    def test_template_without_semicolon(self):
        """Test template without semicolon (just platform)."""
        assert architecture_from_template("x64") == "x64"
        assert architecture_from_template("Intel") == "x86"

    def test_whitespace_handling(self):
        """Test whitespace in template is handled."""
        assert architecture_from_template("  x64  ;1033") == "x64"
        assert architecture_from_template("x64 ; 1033") == "x64"
