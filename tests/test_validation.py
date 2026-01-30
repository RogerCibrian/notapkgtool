"""
Tests for recipe validation module.

This module tests the validation functionality that checks recipe syntax
and configuration without making network calls or downloading files.
"""

from __future__ import annotations

from notapkgtool.validation import validate_recipe


class TestValidateRecipe:
    """Tests for validate_recipe function."""

    def test_valid_recipe_url_download(self, tmp_path):
        """Test that a valid url_download recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_valid_recipe_api_github(self, tmp_path):
        """Test that a valid api_github recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Git"
  id: "git"
  source:
    strategy: api_github
    repo: "git/git"
    asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0

    def test_valid_recipe_web_scrape(self, tmp_path):
        """Test that a valid web_scrape recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: web_scrape
    page_url: "https://example.com/download.html"
    link_selector: 'a[href$=".msi"]'
    version_pattern: "app-v([0-9.]+)\\\\.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0

    def test_valid_recipe_api_json(self, tmp_path):
        """Test that a valid api_json recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: api_json
    api_url: "https://api.example.com/latest"
    version_path: "version"
    download_url_path: "download_url"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0

    def test_missing_file(self, tmp_path):
        """Test that missing recipe file is reported."""
        recipe = tmp_path / "nonexistent.yaml"

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert len(result.errors) == 1
        assert "not found" in result.errors[0]

    def test_invalid_yaml_syntax(self, tmp_path):
        """Test that invalid YAML syntax is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  invalid yaml: [unclosed bracket
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert len(result.errors) == 1
        assert "YAML syntax" in result.errors[0]

    def test_empty_file(self, tmp_path):
        """Test that empty YAML file is handled."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert len(result.errors) >= 1

    def test_non_dict_yaml(self, tmp_path):
        """Test that non-dictionary YAML is rejected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("- item1\n- item2\n")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("dictionary" in err.lower() for err in result.errors)

    def test_missing_api_version(self, tmp_path):
        """Test that missing apiVersion is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
app:
  name: "Test"
  id: "test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("apiVersion" in err for err in result.errors)

    def test_unsupported_api_version_warning(self, tmp_path):
        """Test that unsupported apiVersion generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v99
app:
  name: "Test"
  id: "test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)

        assert len(result.warnings) >= 1
        assert any("napt/v99" in warn for warn in result.warnings)

    def test_missing_app(self, tmp_path):
        """Test that missing app field is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("app" in err for err in result.errors)

    def test_app_not_dict(self, tmp_path):
        """Test that app must be a dictionary."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app: "not a dict"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("dictionary" in err for err in result.errors)

    def test_missing_app_name(self, tmp_path):
        """Test that missing app name is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  id: "test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("name" in err for err in result.errors)

    def test_missing_app_id(self, tmp_path):
        """Test that missing app id is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("id" in err for err in result.errors)

    def test_missing_source(self, tmp_path):
        """Test that missing source is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("source" in err for err in result.errors)

    def test_missing_strategy(self, tmp_path):
        """Test that missing strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("strategy" in err for err in result.errors)

    def test_unknown_strategy(self, tmp_path):
        """Test that unknown strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: nonexistent_strategy
    url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("Unknown" in err or "nonexistent" in err for err in result.errors)

    def test_url_download_missing_url(self, tmp_path):
        """Test that url_download validates missing url."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: url_download
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("url" in err for err in result.errors)

    def test_api_github_missing_repo(self, tmp_path):
        """Test that api_github validates missing repo."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: api_github
    asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("repo" in err for err in result.errors)

    def test_api_github_invalid_repo_format(self, tmp_path):
        """Test that api_github validates repo format."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: api_github
    repo: "invalid-repo-format"
    asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("owner/repo" in err or "format" in err for err in result.errors)

    def test_web_scrape_missing_fields(self, tmp_path):
        """Test that web_scrape validates missing required fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: web_scrape
    page_url: "https://example.com/download.html"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "link_selector" in err or "link_pattern" in err for err in result.errors
        )

    def test_web_scrape_invalid_pattern(self, tmp_path):
        """Test that web_scrape validates regex syntax."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: web_scrape
    page_url: "https://example.com/download.html"
    link_selector: 'a[href$=".msi"]'
    version_pattern: "[unclosed bracket"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("regex" in err.lower() or "pattern" in err for err in result.errors)

    def test_api_json_missing_fields(self, tmp_path):
        """Test that api_json validates missing required fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: api_json
    api_url: "https://api.example.com/latest"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        # Should be missing version_path and download_url_path
        assert len(result.errors) >= 2

    def test_verbose_mode(self, tmp_path, capsys):
        """Test that verbose mode prints progress."""
        from notapkgtool.logging import get_logger, set_global_logger

        # Set up verbose logger
        logger = get_logger(verbose=True, debug=False)
        set_global_logger(logger)

        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)
        captured = capsys.readouterr()

        assert result.status == "valid"
        assert "Validating recipe" in captured.out
        assert "YAML syntax is valid" in captured.out
        assert "url_download" in captured.out

    def test_result_contains_recipe_path(self, tmp_path):
        """Test that result includes the recipe path."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test"
  id: "test"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
    version:
      type: msi
"""
        )

        result = validate_recipe(recipe)

        assert hasattr(result, "recipe_path")
        assert str(recipe) in result.recipe_path


class TestWin32Validation:
    """Tests for win32 configuration validation."""

    def test_valid_win32_config(self, tmp_path):
        """Test that valid win32 config passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    build_types: "both"
    installed_check:
      display_name: "Test App *"
      architecture: "x64"
      override_msi_display_name: false
      fail_on_error: true
      log_rotation_mb: 3
      detection:
        exact_match: false
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_win32_invalid_build_types_value(self, tmp_path):
        """Test that invalid build_types value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    build_types: "invalid"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("build_types" in err and "Invalid value" in err for err in result.errors)

    def test_win32_invalid_build_types_type(self, tmp_path):
        """Test that invalid build_types type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    build_types: 123
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("build_types" in err and "str" in err for err in result.errors)

    def test_win32_unknown_field_warning(self, tmp_path):
        """Test that unknown win32 field generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    buildtypes: "both"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any("Unknown field 'buildtypes'" in warn for warn in result.warnings)
        assert any("build_types" in warn for warn in result.warnings)

    def test_installed_check_invalid_architecture(self, tmp_path):
        """Test that invalid architecture value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      display_name: "Test App"
      architecture: "x128"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("architecture" in err and "Invalid value" in err for err in result.errors)

    def test_installed_check_unknown_field_with_suggestion(self, tmp_path):
        """Test that unknown installed_check field suggests similar field."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      displayname: "Test App"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any(
            "Unknown field 'displayname'" in warn and "display_name" in warn
            for warn in result.warnings
        )

    def test_installed_check_invalid_bool_type(self, tmp_path):
        """Test that invalid boolean type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      override_msi_display_name: "yes"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "override_msi_display_name" in err and "bool" in err for err in result.errors
        )

    def test_installed_check_invalid_int_type(self, tmp_path):
        """Test that invalid integer type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      log_rotation_mb: "three"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("log_rotation_mb" in err and "int" in err for err in result.errors)

    def test_detection_invalid_exact_match_type(self, tmp_path):
        """Test that invalid exact_match type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      detection:
        exact_match: "true"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("exact_match" in err and "bool" in err for err in result.errors)

    def test_detection_unknown_field_warning(self, tmp_path):
        """Test that unknown detection field generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      detection:
        exactmatch: true
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any(
            "Unknown field 'exactmatch'" in warn and "exact_match" in warn
            for warn in result.warnings
        )

    def test_win32_not_dict_error(self, tmp_path):
        """Test that non-dict win32 is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32: "not a dict"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("win32" in err and "dictionary" in err for err in result.errors)

    def test_installed_check_not_dict_error(self, tmp_path):
        """Test that non-dict installed_check is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check: "not a dict"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("installed_check" in err and "dictionary" in err for err in result.errors)

    def test_detection_not_dict_error(self, tmp_path):
        """Test that non-dict detection is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      detection: "not a dict"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("detection" in err and "dictionary" in err for err in result.errors)

    def test_installed_check_invalid_log_level(self, tmp_path):
        """Test that invalid log_level value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    installed_check:
      log_level: "VERBOSE"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("log_level" in err and "Invalid value" in err for err in result.errors)

    def test_multiple_unknown_fields_all_warned(self, tmp_path):
        """Test that multiple unknown fields all generate warnings."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
  win32:
    buildtypes: "both"
    unknownfield: "value"
    installed_check:
      displayname: "Test"
      arch: "x64"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        # Should have warnings for: buildtypes, unknownfield, displayname, arch
        assert len(result.warnings) >= 4

    def test_no_win32_section_is_valid(self, tmp_path):
        """Test that missing win32 section is valid (optional)."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
app:
  name: "Test App"
  id: "test-app"
  source:
    strategy: url_download
    url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
