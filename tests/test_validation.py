"""
Tests for recipe validation module.

This module tests the validation functionality that checks recipe syntax
and configuration without making network calls or downloading files.
"""

from __future__ import annotations

from napt.validation import validate_recipe


class TestValidateRecipe:
    """Tests for validate_recipe function."""

    def test_valid_recipe_url_download(self, tmp_path):
        """Test that a valid url_download recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_valid_recipe_api_github(self, tmp_path):
        """Test that a valid api_github recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Git"
id: "git"
discovery:
  strategy: api_github
  repo: "git/git"
  asset_pattern: ".*\\\\.exe$"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0

    def test_valid_recipe_web_scrape(self, tmp_path):
        """Test that a valid web_scrape recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: web_scrape
  page_url: "https://example.com/download.html"
  link_selector: 'a[href$=".msi"]'
  version_pattern: "app-v([0-9.]+)\\\\.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert result.app_count == 1
        assert len(result.errors) == 0

    def test_valid_recipe_api_json(self, tmp_path):
        """Test that a valid api_json recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: api_json
  api_url: "https://api.example.com/latest"
  version_path: "version"
  download_url_path: "download_url"
""")

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
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
  invalid yaml: [unclosed bracket
""")

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
        recipe.write_text("""
name: "Test"
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("apiVersion" in err for err in result.errors)

    def test_unsupported_api_version_warning(self, tmp_path):
        """Test that unsupported apiVersion generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v99
name: "Test"
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert len(result.warnings) >= 1
        assert any("napt/v99" in warn for warn in result.warnings)

    def test_missing_name(self, tmp_path):
        """Test that missing name field is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("name" in err for err in result.errors)

    def test_missing_id(self, tmp_path):
        """Test that missing id field is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("id" in err for err in result.errors)

    def test_missing_discovery(self, tmp_path):
        """Test that missing discovery section is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("discovery" in err for err in result.errors)

    def test_missing_strategy(self, tmp_path):
        """Test that missing strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("strategy" in err for err in result.errors)

    def test_unknown_strategy(self, tmp_path):
        """Test that unknown strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: nonexistent_strategy
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("Unknown" in err or "nonexistent" in err for err in result.errors)

    def test_url_download_missing_url(self, tmp_path):
        """Test that url_download validates missing url."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: url_download
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("url" in err for err in result.errors)

    def test_api_github_missing_repo(self, tmp_path):
        """Test that api_github validates missing repo."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: api_github
  asset_pattern: ".*\\\\.exe$"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("repo" in err for err in result.errors)

    def test_api_github_invalid_repo_format(self, tmp_path):
        """Test that api_github validates repo format."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: api_github
  repo: "invalid-repo-format"
  asset_pattern: ".*\\\\.exe$"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("owner/repo" in err or "format" in err for err in result.errors)

    def test_web_scrape_missing_fields(self, tmp_path):
        """Test that web_scrape validates missing required fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: web_scrape
  page_url: "https://example.com/download.html"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "link_selector" in err or "link_pattern" in err for err in result.errors
        )

    def test_web_scrape_invalid_pattern(self, tmp_path):
        """Test that web_scrape validates regex syntax."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: web_scrape
  page_url: "https://example.com/download.html"
  link_selector: 'a[href$=".msi"]'
  version_pattern: "[unclosed bracket"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("regex" in err.lower() or "pattern" in err for err in result.errors)

    def test_api_json_missing_fields(self, tmp_path):
        """Test that api_json validates missing required fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: api_json
  api_url: "https://api.example.com/latest"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert len(result.errors) >= 2

    def test_verbose_mode(self, tmp_path, capsys):
        """Test that verbose mode prints progress."""
        from napt.logging import get_logger, set_global_logger

        logger = get_logger(verbose=True, debug=False)
        set_global_logger(logger)

        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)
        captured = capsys.readouterr()

        assert result.status == "valid"
        assert "Validating recipe" in captured.out
        assert "YAML syntax is valid" in captured.out
        assert "url_download" in captured.out

    def test_result_contains_recipe_path(self, tmp_path):
        """Test that result includes the recipe path."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert hasattr(result, "recipe_path")
        assert str(recipe) in result.recipe_path


class TestIntuneValidation:
    """Tests for intune: section validation."""

    def test_valid_intune_detection(self, tmp_path):
        """Test that valid intune.detection config passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  build_types: "both"
  detection:
    display_name: "Test App *"
    architecture: "x64"
    override_msi_display_name: false
    exact_match: false
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_intune_invalid_build_types_value(self, tmp_path):
        """Test that invalid build_types value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  build_types: "invalid"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "build_types" in err and "Invalid value" in err for err in result.errors
        )

    def test_intune_invalid_build_types_type(self, tmp_path):
        """Test that invalid build_types type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  build_types: 123
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("build_types" in err and "str" in err for err in result.errors)

    def test_intune_unknown_field_warning(self, tmp_path):
        """Test that unknown intune field generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  buildtypes: "both"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any("Unknown field 'buildtypes'" in warn for warn in result.warnings)
        assert any("build_types" in warn for warn in result.warnings)

    def test_detection_invalid_architecture(self, tmp_path):
        """Test that invalid architecture value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection:
    display_name: "Test App"
    architecture: "x128"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "architecture" in err and "Invalid value" in err for err in result.errors
        )

    def test_detection_unknown_field_with_suggestion(self, tmp_path):
        """Test that unknown detection field suggests similar field."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection:
    displayname: "Test App"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any(
            "Unknown field 'displayname'" in warn and "display_name" in warn
            for warn in result.warnings
        )

    def test_detection_invalid_bool_type(self, tmp_path):
        """Test that invalid boolean type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection:
    override_msi_display_name: "yes"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "override_msi_display_name" in err and "bool" in err
            for err in result.errors
        )

    def test_detection_invalid_exact_match_type(self, tmp_path):
        """Test that invalid exact_match type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection:
    exact_match: "true"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("exact_match" in err and "bool" in err for err in result.errors)

    def test_detection_unknown_field_warning(self, tmp_path):
        """Test that unknown detection field generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection:
    exactmatch: true
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert any(
            "Unknown field 'exactmatch'" in warn and "exact_match" in warn
            for warn in result.warnings
        )

    def test_intune_not_dict_error(self, tmp_path):
        """Test that non-dict intune section is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune: "not a dict"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("intune" in err and "dictionary" in err for err in result.errors)

    def test_detection_not_dict_error(self, tmp_path):
        """Test that non-dict detection is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  detection: "not a dict"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("detection" in err and "dictionary" in err for err in result.errors)

    def test_no_intune_section_is_valid(self, tmp_path):
        """Test that missing intune section is valid (optional)."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_multiple_unknown_fields_all_warned(self, tmp_path):
        """Test that multiple unknown fields all generate warnings."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
intune:
  buildtypes: "both"
  unknownfield: "value"
  detection:
    displayname: "Test"
    arch: "x64"
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.warnings) >= 4


class TestLoggingValidation:
    """Tests for logging: section validation."""

    def test_valid_logging_section(self, tmp_path):
        """Test that valid logging config passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
logging:
  log_format: "cmtrace"
  log_level: "INFO"
  log_rotation_mb: 5
""")

        result = validate_recipe(recipe)

        assert result.status == "valid"
        assert len(result.errors) == 0

    def test_logging_invalid_log_level(self, tmp_path):
        """Test that invalid log_level value is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
logging:
  log_level: "VERBOSE"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any(
            "log_level" in err and "Invalid value" in err for err in result.errors
        )

    def test_logging_invalid_log_rotation_type(self, tmp_path):
        """Test that invalid log_rotation_mb type is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
logging:
  log_rotation_mb: "three"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("log_rotation_mb" in err and "int" in err for err in result.errors)

    def test_logging_not_dict_error(self, tmp_path):
        """Test that non-dict logging section is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
logging: "not a dict"
""")

        result = validate_recipe(recipe)

        assert result.status == "invalid"
        assert any("logging" in err and "dictionary" in err for err in result.errors)
