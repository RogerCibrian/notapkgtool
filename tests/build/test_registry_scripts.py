"""Tests for napt.build.registry_scripts: the registry detection and
requirements scripts, their config dataclasses, and the MSI entry filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from napt.build.registry_scripts import (
    DetectionConfig,
    RequirementsConfig,
    generate_detection_script,
    generate_requirements_script,
)

# All tests in this file are unit tests (fast, mocked)


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
        assert config.log_rotation_mb == 3
        assert config.exact_match is False
        assert config.is_msi_installer is False
        assert config.expected_architecture == "any"
        assert config.use_wildcard is False

    def test_custom_values(self):
        """Test custom values for DetectionConfig."""
        config = DetectionConfig(
            app_name="Custom App",
            version="2.5.0",
            log_rotation_mb=10,
            exact_match=True,
            is_msi_installer=True,
        )

        assert config.app_name == "Custom App"
        assert config.version == "2.5.0"
        assert config.log_rotation_mb == 10
        assert config.exact_match is True
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

    def test_line_break_in_app_name_cannot_add_a_statement(self, tmp_path: Path):
        """Tests that a name with a line break stays inside the comment line."""
        config = DetectionConfig(
            app_name="Contoso Viewer\r\nusing module \\\\evil\\share\\x.psm1",
            version="1.0.0",
        )
        output_path = tmp_path / "Contoso_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        lines = output_path.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0].startswith("# Detection script for Contoso Viewer using")
        assert not any(line.startswith("using module") for line in lines)

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
        assert "Found: Non-MSI, Expected: MSI" in content
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

    def test_script_checks_registry_using_openbasekey(self, tmp_path: Path):
        """Test that script uses OpenBaseKey for explicit registry view access."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for OpenBaseKey usage (new architecture-aware approach)
        assert "OpenBaseKey" in content
        assert "RegistryHive" in content
        assert "RegistryView" in content
        # Check that it accesses the Uninstall path
        assert "Uninstall" in content
        # Check for both HKLM and HKCU hives
        assert "LocalMachine" in content
        assert "CurrentUser" in content

    def test_script_component_ends_with_detection(self, tmp_path: Path):
        """Test that CMTrace component name ends with -Detection."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Component is built at runtime from
        # $SanitizedAppName-$ExpectedVersion-Detection
        assert "ComponentName" in content and '-Detection"' in content

    def test_script_result_not_detected_logs_as_warning(self, tmp_path: Path):
        """Test that Not Detected result is logged as WARNING for visibility."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "[Result] Not Detected:" in content
        idx = content.find("[Result] Not Detected:")
        # Excerpt must include -Type "WARNING" (message is long)
        excerpt = content[idx : idx + 350]
        assert "WARNING" in excerpt

    def test_script_contains_expected_architecture_parameter(self, tmp_path: Path):
        """Test that script contains ExpectedArchitecture parameter."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="x64",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "$ExpectedArchitecture" in content
        assert '"x64"' in content

    def test_script_x64_uses_registry64_view(self, tmp_path: Path):
        """Test that x64 architecture uses Registry64 view."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="x64",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for OpenBaseKey with RegistryView
        assert "OpenBaseKey" in content
        assert "RegistryView" in content
        assert "Registry64" in content

    def test_script_x86_uses_registry32_view(self, tmp_path: Path):
        """Test that x86 architecture uses Registry32 view."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="x86",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "Registry32" in content

    def test_script_any_checks_both_views(self, tmp_path: Path):
        """Test that 'any' architecture checks both registry views."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="any",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # 'any' mode should check both views
        assert "Registry64" in content
        assert "Registry32" in content

    def test_script_arm64_uses_registry64_view(self, tmp_path: Path):
        """Tests that arm64 uses the Registry64 view, as ARM64 Windows does."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="arm64",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "Registry64" in content
        assert "ARM64" in content or "arm64" in content.lower()

    def test_script_logs_architecture_in_initialization(self, tmp_path: Path):
        """Test that script logs architecture during initialization."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            expected_architecture="x64",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "Architecture:" in content

    def test_script_uses_eq_by_default(self, tmp_path: Path):
        """Test that script uses -eq for DisplayName matching by default."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
            use_wildcard=False,
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for exact -eq matching
        assert "$DisplayNameValue -eq $AppName" in content

    def test_script_uses_like_with_wildcard(self, tmp_path: Path):
        """Test that script uses -like when use_wildcard is True."""
        config = DetectionConfig(
            app_name="7-Zip *",
            version="25.01",
            use_wildcard=True,
        )
        output_path = tmp_path / "7-Zip_25.01-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for -like matching
        assert "$DisplayNameValue -like $AppName" in content

    def test_script_wildcard_with_question_mark(self, tmp_path: Path):
        """Test that script uses -like when use_wildcard is True with ? wildcard."""
        config = DetectionConfig(
            app_name="7-Zip ??.??",
            version="24.09",
            use_wildcard=True,
        )
        output_path = tmp_path / "7-Zip_24.09-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for -like matching
        assert "$DisplayNameValue -like $AppName" in content
        # Check app name is in script
        assert "7-Zip ??.??" in content

    def test_no_unreplaced_napt_variables(self, tmp_path: Path):
        """Tests that all $Napt* variables are substituted."""
        config = DetectionConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Detection.ps1"

        generate_detection_script(config, output_path)

        content = output_path.read_text(encoding="utf-8")

        import re

        remaining = re.findall(r"\$Napt[A-Z]\w*", content)
        assert remaining == [], f"Unreplaced $Napt* variables: {remaining}"


def test_detection_script_write_failure_is_a_packaging_error(tmp_path):
    """Tests that a script the file system refuses to write is reported as a
    packaging error naming the path, not an OSError traceback."""
    from napt.exceptions import PackagingError

    config = DetectionConfig(app_name="Test App", version="1.0.0")
    output_path = tmp_path / "detection.ps1"
    output_path.mkdir()  # a directory where the file should go

    with pytest.raises(PackagingError, match="detection.ps1"):
        generate_detection_script(config, output_path)


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
        assert config.log_rotation_mb == 3
        assert config.expected_architecture == "any"
        assert config.use_wildcard is False

    def test_custom_values(self):
        """Test custom values for RequirementsConfig."""
        config = RequirementsConfig(
            app_name="Custom App",
            version="2.5.0",
            log_rotation_mb=10,
        )

        assert config.app_name == "Custom App"
        assert config.version == "2.5.0"
        assert config.log_rotation_mb == 10

    def test_default_is_msi_installer(self):
        """Test default value of is_msi_installer is False."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )

        assert config.is_msi_installer is False

    def test_is_msi_installer_true(self):
        """Test is_msi_installer can be set to True."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )

        assert config.is_msi_installer is True


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
        assert "Compare-VersionString" in content
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

    def test_script_checks_registry_using_openbasekey(self, tmp_path: Path):
        """Test that script uses OpenBaseKey for explicit registry view access."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for OpenBaseKey usage (new architecture-aware approach)
        assert "OpenBaseKey" in content
        assert "RegistryHive" in content
        assert "RegistryView" in content
        # Check that it accesses the Uninstall path
        assert "Uninstall" in content
        # Check for both HKLM and HKCU hives
        assert "LocalMachine" in content
        assert "CurrentUser" in content

    def test_script_contains_msi_installer_parameter(self, tmp_path: Path):
        """Test that script contains IsMSIInstaller parameter."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for IsMSIInstaller parameter
        assert "$IsMSIInstaller" in content
        assert "$True" in content  # MSI installer mode

    def test_script_contains_test_msi_installation_function(self, tmp_path: Path):
        """Test that script contains Test-IsMSIInstallation function."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for Test-IsMSIInstallation function
        assert "function Test-IsMSIInstallation" in content
        # Check for WindowsInstaller check (authoritative MSI indicator)
        assert "WindowsInstaller" in content

    def test_script_non_msi_installer(self, tmp_path: Path):
        """Test that script has $False for non-MSI installer."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=False,
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check that IsMSIInstaller is False
        assert "[bool]$IsMSIInstaller = $False" in content

    def test_script_msi_strict_non_msi_permissive(self, tmp_path: Path):
        """Test that MSI matching is strict but non-MSI is permissive.

        MSI installers: only match MSI registry entries (strict)
        Non-MSI installers: match any entry (permissive, EXEs may use embedded MSIs)
        """
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for MSI strict check (skips non-MSI entries when building from MSI)
        assert "Found: Non-MSI, Expected: MSI" in content
        # Check that non-MSI is permissive (accepts any entry)
        assert "Non-MSI installers accept ANY registry entry" in content

    def test_script_logs_installer_type(self, tmp_path: Path):
        """Test that script logs installer type during initialization."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            is_msi_installer=True,
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for installer type in initialization logging
        assert "Installer Type:" in content

    def test_script_component_ends_with_requirements(self, tmp_path: Path):
        """Test that CMTrace component name ends with -Requirements (not -Req)."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Component is built at runtime from
        # $SanitizedAppName-$TargetVersion-Requirements
        assert "ComponentName" in content and '-Requirements"' in content

    def test_script_result_update_not_required_logs_as_warning(self, tmp_path: Path):
        """Tests that an Update Not Required result is logged as WARNING."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        assert "[Result] Update Not Required:" in content
        idx = content.find("[Result] Update Not Required:")
        excerpt = content[idx : idx + 300]
        assert "WARNING" in excerpt

    def test_script_uses_eq_by_default(self, tmp_path: Path):
        """Test that script uses -eq for DisplayName matching by default."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
            use_wildcard=False,
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for exact -eq matching
        assert "$DisplayNameValue -eq $AppName" in content

    def test_script_uses_like_with_wildcard(self, tmp_path: Path):
        """Test that script uses -like when use_wildcard is True."""
        config = RequirementsConfig(
            app_name="7-Zip *",
            version="25.01",
            use_wildcard=True,
        )
        output_path = tmp_path / "7-Zip_25.01-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for -like matching
        assert "$DisplayNameValue -like $AppName" in content

    def test_script_wildcard_with_question_mark(self, tmp_path: Path):
        """Test that script uses -like when use_wildcard is True with ? wildcard."""
        config = RequirementsConfig(
            app_name="7-Zip ??.??",
            version="24.09",
            use_wildcard=True,
        )
        output_path = tmp_path / "7-Zip_24.09-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8-sig")

        # Check for -like matching
        assert "$DisplayNameValue -like $AppName" in content
        # Check app name is in script
        assert "7-Zip ??.??" in content

    def test_no_unreplaced_napt_variables(self, tmp_path: Path):
        """Tests that all $Napt* variables are substituted."""
        config = RequirementsConfig(
            app_name="Test App",
            version="1.0.0",
        )
        output_path = tmp_path / "Test-App_1.0.0-Requirements.ps1"

        generate_requirements_script(config, output_path)

        content = output_path.read_text(encoding="utf-8")

        import re

        remaining = re.findall(r"\$Napt[A-Z]\w*", content)
        assert remaining == [], f"Unreplaced $Napt* variables: {remaining}"


def test_requirements_script_write_failure_is_a_packaging_error(tmp_path):
    """Tests that a script the file system refuses to write is reported as a
    packaging error naming the path, not an OSError traceback."""
    from napt.exceptions import PackagingError

    config = RequirementsConfig(app_name="Test App", version="1.0.0")
    output_path = tmp_path / "requirements.ps1"
    output_path.mkdir()  # a directory where the file should go

    with pytest.raises(PackagingError, match="requirements.ps1"):
        generate_requirements_script(config, output_path)
