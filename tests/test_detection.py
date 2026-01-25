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

"""Tests for notapkgtool.detection module.

Tests detection script generation including:
- Script content validation (log paths, output)
- Script filename conventions
- DetectionConfig dataclass
- MSI installer type filtering
"""

from __future__ import annotations

from pathlib import Path

import pytest

from notapkgtool.detection import (
    DetectionConfig,
    generate_detection_script,
    sanitize_filename,
)

# All tests in this file are unit tests (fast, mocked)
pytestmark = pytest.mark.unit


class TestDetectionConfig:
    """Tests for DetectionConfig dataclass."""

    def test_default_values(self):
        """Test default values for DetectionConfig."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )

        assert config.app_name == "Test App"
        assert config.version == "1.0.0"
        assert config.log_format == "cmtrace"
        assert config.log_level == "INFO"
        assert config.log_rotation_mb == 3
        assert config.exact_match is False
        assert config.app_id == ""
        assert config.is_msi_installer is False

    def test_custom_values(self):
        """Test custom values for DetectionConfig."""
        config = DetectionConfig(
            app_name="Custom App",
            version="2.5.0",
            log_format="cmtrace",
            log_level="DEBUG",
            log_rotation_mb=10,
            exact_match=True,
            app_id="custom-app",
            is_msi_installer=True,
        )

        assert config.app_name == "Custom App"
        assert config.version == "2.5.0"
        assert config.log_level == "DEBUG"
        assert config.log_rotation_mb == 10
        assert config.exact_match is True
        assert config.app_id == "custom-app"
        assert config.is_msi_installer is True

    def test_default_is_msi_installer(self):
        """Test default value of is_msi_installer is False."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )

        assert config.is_msi_installer is False

    def test_is_msi_installer_true(self):
        """Test is_msi_installer can be set to True."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )

        assert config.is_msi_installer is True


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_basic_sanitization(self):
        """Test basic sanitization of app names."""
        assert sanitize_filename("Google Chrome") == "Google-Chrome"
        assert sanitize_filename("My App v2.0") == "My-App-v2.0"

    def test_removes_invalid_chars(self):
        """Test removal of invalid Windows filename characters."""
        assert sanitize_filename("Test<>App") == "TestApp"
        assert sanitize_filename('App:Name|"Test"') == "AppNameTest"

    def test_fallback_to_app_id(self):
        """Test fallback to app_id when name becomes empty."""
        assert sanitize_filename("  ", "my-app") == "my-app"
        assert sanitize_filename("", "test") == "test"

    def test_fallback_to_default(self):
        """Test fallback to 'app' when name and app_id are empty."""
        assert sanitize_filename("") == "app"
        assert sanitize_filename("   ") == "app"


class TestGenerateDetectionScript:
    """Tests for detection script generation."""

    def test_script_filename_ends_with_detection(self, tmp_path: Path):
        """Test that script filename ends with -Detection.ps1."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        result = generate_detection_script(config, output_path)

        assert result.name.endswith("-Detection.ps1")
        assert result.exists()

    def test_script_contains_napt_detections_log_paths(self, tmp_path: Path):
        """Test that script contains NAPTDetections.log paths."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for system context log paths
        assert "NAPTDetections.log" in content
        assert "NAPTDetectionsUser.log" in content

    def test_script_substitutes_app_name(self, tmp_path: Path):
        """Test that app name is correctly substituted."""
        config = DetectionConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        output_path = tmp_path / "Google-Chrome_131.0.6778.86-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check app name in script
        assert "Google Chrome" in content
        assert "131.0.6778.86" in content

    def test_script_has_utf8_bom(self, tmp_path: Path):
        """Test that script is written with UTF-8 BOM encoding."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        # Read raw bytes to check for BOM
        content_bytes = output_path.read_bytes()
        # UTF-8 BOM is: EF BB BF
        assert content_bytes[:3] == b"\xef\xbb\xbf"

    def test_script_creates_parent_directory(self, tmp_path: Path):
        """Test that parent directory is created if it doesn't exist."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "nested" / "path" / "Test-App_1.0.0-Detection.ps1"

        result = generate_detection_script(config, output_path)

        assert result.exists()
        assert result.parent.exists()

    def test_script_contains_msi_installer_parameter(self, tmp_path: Path):
        """Test that script contains IsMSIInstaller parameter."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for IsMSIInstaller parameter
        assert "$IsMSIInstaller" in content
        assert "$True" in content  # MSI installer mode

    def test_script_contains_test_msi_installation_function(self, tmp_path: Path):
        """Test that script contains Test-IsMSIInstallation function."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for Test-IsMSIInstallation function
        assert "function Test-IsMSIInstallation" in content
        # Check for WindowsInstaller check (authoritative MSI indicator)
        assert "WindowsInstaller" in content

    def test_script_non_msi_installer(self, tmp_path: Path):
        """Test that script has $False for non-MSI installer."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=False,
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check that IsMSIInstaller is False
        assert "[bool]$IsMSIInstaller = $False" in content

    def test_script_msi_strict_non_msi_permissive(self, tmp_path: Path):
        """Test that MSI matching is strict but non-MSI is permissive.

        MSI installers: only match MSI registry entries (strict)
        Non-MSI installers: match any entry (permissive, EXEs may use embedded MSIs)
        """
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for MSI strict check (skips non-MSI entries when building from MSI)
        assert "expected MSI - skipping" in content
        # Check that non-MSI is permissive (accepts any entry)
        assert "Non-MSI installers accept ANY registry entry" in content

    def test_script_logs_installer_type(self, tmp_path: Path):
        """Test that script logs installer type during initialization."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for installer type in initialization logging
        assert "Installer Type:" in content

    def test_script_exact_match_mode(self, tmp_path: Path):
        """Test that exact_match mode is substituted correctly."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            exact_match=True,
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for ExactMatch parameter with True value
        assert "[bool]$ExactMatch = $True" in content

    def test_script_checks_all_registry_paths(self, tmp_path: Path):
        """Test that script checks all registry paths (HKLM, HKCU, Wow6432Node)."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for registry paths
        assert (
            "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in content
        )
        assert (
            "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in content
        )
        assert "WOW6432Node" in content

    def test_script_component_ends_with_detection(self, tmp_path: Path):
        """Test that CMTrace component name ends with -Detection."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Component is built at runtime from $SanitizedAppName-$ExpectedVersion-Detection
        assert "ComponentName" in content and '-Detection"' in content

    def test_script_result_failed_logs_as_warning(self, tmp_path: Path):
        """Test that Detection FAILED result is logged as WARNING for visibility."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "[Result] Detection FAILED:" in content
        idx = content.find("[Result] Detection FAILED:")
        # Excerpt must include -Type "WARNING" (message is long)
        excerpt = content[idx : idx + 350]
        assert "WARNING" in excerpt
