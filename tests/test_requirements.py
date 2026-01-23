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

"""Tests for notapkgtool.requirements module.

Tests requirements script generation including:
- Script content validation (log paths, Required output)
- Script filename conventions
- RequirementsConfig dataclass
"""

from __future__ import annotations

from pathlib import Path

import pytest

from notapkgtool.requirements import (
    RequirementsConfig,
    generate_requirements_script,
)

# All tests in this file are unit tests (fast, mocked)
pytestmark = pytest.mark.unit


class TestRequirementsConfig:
    """Tests for RequirementsConfig dataclass."""

    def test_default_values(self):
        """Test default values for RequirementsConfig."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )

        assert config.app_name == "Test App"
        assert config.version == "1.0.0"
        assert config.log_format == "cmtrace"
        assert config.log_level == "INFO"
        assert config.log_rotation_mb == 3
        assert config.app_id == ""

    def test_custom_values(self):
        """Test custom values for RequirementsConfig."""
        config = RequirementsConfig(
            app_name="Custom App",
            version="2.5.0",
            log_format="cmtrace",
            log_level="DEBUG",
            log_rotation_mb=10,
            app_id="custom-app",
        )

        assert config.app_name == "Custom App"
        assert config.version == "2.5.0"
        assert config.log_level == "DEBUG"
        assert config.log_rotation_mb == 10
        assert config.app_id == "custom-app"


class TestGenerateRequirementsScript:
    """Tests for requirements script generation."""

    def test_script_filename_ends_with_requirements(self, tmp_path: Path):
        """Test that script filename ends with -Requirements.ps1."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        result = generate_requirements_script(config, output_path)

        assert result.name.endswith("-Requirements.ps1")
        assert result.exists()

    def test_script_contains_napt_requirements_log_paths(self, tmp_path: Path):
        """Test that script contains NAPTRequirements.log paths."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for system context log paths
        assert "NAPTRequirements.log" in content
        assert "NAPTRequirementsUser.log" in content
        # Ensure it's NOT using the detection log names
        assert "NAPTDetections.log" not in content
        assert "NAPTDetectionsUser.log" not in content

    def test_script_contains_primary_log_paths(self, tmp_path: Path):
        """Test that script contains correct primary log directory."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for Intune log directory
        assert "C:\\ProgramData\\Microsoft\\IntuneManagementExtension\\Logs" in content
        # Check for fallback directory
        assert "C:\\ProgramData\\NAPT" in content

    def test_script_outputs_required_when_older_version(self, tmp_path: Path):
        """Test that script contains logic to output 'Required' for older versions."""
        config = RequirementsConfig(
            app_name="Test App",
            version="2.0.0",
        )
        output_path = tmp_path / "Test-App_2.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for Required output logic
        assert 'Write-Output "Required"' in content
        # Check for version comparison function
        assert "Compare-VersionLessThan" in content
        # Check that script always exits 0
        assert "exit 0" in content

    def test_script_uses_target_version_parameter(self, tmp_path: Path):
        """Test that script uses TargetVersion parameter (not ExpectedVersion)."""
        config = RequirementsConfig(
            app_name="Test App",
            version="3.5.0",
        )
        output_path = tmp_path / "Test-App_3.5.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for TargetVersion parameter (requirements-specific)
        assert "$TargetVersion" in content
        assert '"3.5.0"' in content

    def test_script_substitutes_app_name(self, tmp_path: Path):
        """Test that app name is correctly substituted."""
        config = RequirementsConfig(
            app_name="Google Chrome",
            version="131.0.6778.86",
        )
        output_path = tmp_path / "Google-Chrome_131.0.6778.86-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check app name in script
        assert "Google Chrome" in content
        assert "131.0.6778.86" in content

    def test_script_substitutes_log_rotation(self, tmp_path: Path):
        """Test that log rotation size is correctly substituted."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            log_rotation_mb=5,
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for log rotation size
        assert "5 * 1024 * 1024" in content

    def test_script_has_utf8_bom(self, tmp_path: Path):
        """Test that script is written with UTF-8 BOM encoding."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        # Read raw bytes to check for BOM
        content_bytes = output_path.read_bytes()
        # UTF-8 BOM is: EF BB BF
        assert content_bytes[:3] == b"\xef\xbb\xbf"

    def test_script_creates_parent_directory(self, tmp_path: Path):
        """Test that parent directory is created if it doesn't exist."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "nested" / "path" / "Test-App_1.0.0-Requirements.ps1"

        result = generate_requirements_script(config, output_path)

        assert result.exists()
        assert result.parent.exists()

    def test_script_header_comment(self, tmp_path: Path):
        """Test that script has correct header comment."""
        config = RequirementsConfig(
            app_name="My App",
            version="1.2.3",
        )
        output_path = tmp_path / "My-App_1.2.3-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check header comment
        assert "# Requirements script for My App 1.2.3" in content
        assert "# Generated by NAPT" in content
        assert 'Outputs "Required"' in content

    def test_script_checks_all_registry_paths(self, tmp_path: Path):
        """Test that script checks all registry paths (HKLM, HKCU, Wow6432Node)."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for registry paths
        assert "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in content
        assert "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in content
        assert "WOW6432Node" in content
