"""
Tests for recipe validation module.

This module tests the validation functionality that checks recipe syntax
and configuration without making network calls or downloading files.
"""

from __future__ import annotations

import pytest

from napt.validation import validate_recipe, validate_recipes


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

        assert result.is_valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_valid_result_carries_the_effective_config(self, tmp_path):
        """Tests that a valid recipe's result holds the merged configuration
        with its provenance, so a caller need not merge it again."""
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

        assert result.config is not None
        assert result.config["id"] == "test-app"
        assert result.config["directories"]["state"] == "state"
        assert result.config["_provenance"]["id"] == "recipe"
        assert "parent" not in result.config

    def test_invalid_result_has_no_config(self, tmp_path):
        """Tests that a recipe with errors yields no configuration to use."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("apiVersion: napt/v1\nname: App\n")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert result.config is None

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

        assert result.is_valid
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

        assert result.is_valid
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

        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_file(self, tmp_path):
        """Test that missing recipe file is reported."""
        recipe = tmp_path / "nonexistent.yaml"

        result = validate_recipe(recipe)

        assert not result.is_valid
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

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "parsing YAML" in result.errors[0]

    def test_empty_file(self, tmp_path):
        """Test that empty YAML file is handled."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert len(result.errors) >= 1

    def test_non_dict_yaml(self, tmp_path):
        """Test that non-dictionary YAML is rejected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("- item1\n- item2\n")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("mapping" in err.lower() for err in result.errors)

    def test_missing_api_version(self, tmp_path):
        """Test that missing apiVersion is detected."""
        # An org.yaml of its own, so the walk upward does not reach a
        # defaults/org.yaml that supplies apiVersion.
        (tmp_path / "defaults").mkdir()
        (tmp_path / "defaults" / "org.yaml").write_text(
            "logging:\n  log_rotation_mb: 3\n"
        )
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
name: "Test"
id: "test"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
        assert any("id" in err for err in result.errors)

    @pytest.mark.parametrize(
        "app_id", ["../evil", "a/b", "..", "my app", "$(calc)", ".hidden", "NUL"]
    )
    def test_id_that_is_not_a_folder_name_is_invalid(self, tmp_path, app_id):
        """Tests that an id unusable as a folder name is rejected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(f"""
apiVersion: napt/v1
name: "Test"
id: "{app_id}"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("Field 'id' may contain only" in err for err in result.errors)

    @pytest.mark.parametrize(
        "app_id", ["google-chrome", "7zip-x64-msi", "git", "notepad-plus-plus"]
    )
    def test_recommended_id_form_passes_silently(self, tmp_path, app_id):
        """Tests that a <vendor>-<app> id is valid with no warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(f"""
apiVersion: napt/v1
name: "Test"
id: "{app_id}"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert not any("recommended form" in w for w in result.warnings)

    @pytest.mark.parametrize(
        "app_id", ["Google-Chrome", "google_chrome", "google.chrome", "a--b", "x+y"]
    )
    def test_id_outside_the_recommended_form_warns(self, tmp_path, app_id):
        """Tests that a legal but unconventional id is a warning, not an error."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(f"""
apiVersion: napt/v1
name: "Test"
id: "{app_id}"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any(
            f"id '{app_id}' works but does not follow the recommended form" in w
            for w in result.warnings
        )

    def test_missing_discovery(self, tmp_path):
        """Test that missing discovery section is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test"
id: "test"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
        assert any("url" in err for err in result.errors)

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

        assert result.is_valid
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


class TestPsadtValidation:
    """Tests for psadt: section validation."""

    def test_override_msi_commands_must_be_bool(self, tmp_path):
        """Tests that a non-boolean override_msi_commands is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
psadt:
  override_msi_commands: "yes"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("override_msi_commands" in err for err in result.errors)

    def test_override_msi_commands_bool_is_valid(self, tmp_path):
        """Tests that a boolean override_msi_commands passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
psadt:
  override_msi_commands: true
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_override_msix_commands_must_be_bool(self, tmp_path):
        """Tests that a non-boolean override_msix_commands is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msix"
psadt:
  override_msix_commands: 1
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("override_msix_commands" in err for err in result.errors)


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

        assert result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert result.is_valid
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

        assert not result.is_valid
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

        assert result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert result.is_valid
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

        assert not result.is_valid
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

        assert not result.is_valid
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

        assert result.is_valid
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

        assert result.is_valid
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
  log_rotation_mb: 5
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_logging_unknown_field_warning(self, tmp_path):
        """Tests that a removed or unknown logging field generates a warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
logging:
  log_level: "INFO"
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any("Unknown field 'log_level'" in warn for warn in result.warnings)

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

        assert not result.is_valid
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

        assert not result.is_valid
        assert any("logging" in err and "dictionary" in err for err in result.errors)


_DEPLOYMENT_RECIPE_HEADER = """
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
"""


class TestDeploymentValidation:
    """Tests for deployment: section validation."""

    def test_valid_deployment_section(self, tmp_path):
        """Tests that a full valid deployment config passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  require_pending: true
  retain_versions: 2
  rings:
    - name: "pilot"
      groups: ["sg-pilot"]
      promote_after_days: 2
    - name: "production"
      groups: ["sg-prod-a", "sg-prod-b"]
  install:
    intent: "available"
    groups: ["All Users"]
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_ring_missing_name_error(self, tmp_path):
        """Tests that a ring without a name is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  rings:
    - groups: ["sg-pilot"]
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("rings[0]" in err and "name" in err for err in result.errors)

    def test_ring_missing_groups_error(self, tmp_path):
        """Tests that a ring without groups is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  rings:
    - name: "pilot"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("rings[0]" in err and "groups" in err for err in result.errors)

    def test_duplicate_ring_name_error(self, tmp_path):
        """Tests that duplicate ring names are detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  rings:
    - name: "pilot"
      groups: ["sg-a"]
    - name: "pilot"
      groups: ["sg-b"]
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("Duplicate ring name" in err for err in result.errors)

    def test_negative_promote_after_days_error(self, tmp_path):
        """Tests that a negative promote_after_days is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  rings:
    - name: "pilot"
      groups: ["sg-a"]
      promote_after_days: -1
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("promote_after_days" in err for err in result.errors)

    def test_invalid_install_intent_error(self, tmp_path):
        """Tests that an unknown install intent is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  install:
    intent: "mandatory"
    groups: ["All Users"]
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any(
            "deployment.install.intent" in err and "Invalid value" in err
            for err in result.errors
        )

    def test_wrong_typed_ring_field_reports_one_error(self, tmp_path):
        """Tests that a wrong-typed ring field produces exactly one error."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  rings:
    - name: "pilot"
      groups: "sg-a"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        groups_errors = [e for e in result.errors if "groups" in e]
        assert len(groups_errors) == 1
        assert "Must be list" in groups_errors[0]

    def test_virtual_targets_valid(self, tmp_path):
        """Tests that Intune's built-in targets pass validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  install:
    intent: "available"
    groups: ["All Users", "All Devices"]
""")

        result = validate_recipe(recipe)

        assert result.is_valid

    def test_non_string_group_error(self, tmp_path):
        """Tests that a non-string group entry is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  install:
    groups: ["ok", 42]
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("groups[1]" in err for err in result.errors)

    def test_negative_retain_versions_error(self, tmp_path):
        """Tests that a negative retain_versions is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  retain_versions: -1
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("retain_versions" in err for err in result.errors)

    def test_unknown_deployment_field_warns(self, tmp_path):
        """Tests that an unknown deployment field produces a warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER + """
deployment:
  bake_days: 3
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any("Unknown field 'bake_days'" in w for w in result.warnings)


class TestParentValidation:
    """Tests for the parent field and the .override.yaml naming convention."""

    @staticmethod
    def _write_parent(tmp_path, body: str = _DEPLOYMENT_RECIPE_HEADER):
        parent = tmp_path / "base.yaml"
        parent.write_text(body)
        return parent

    def test_override_with_parent_is_valid(self, tmp_path):
        """Tests that an override lacking discovery is valid through its parent."""
        parent = self._write_parent(tmp_path)
        override = tmp_path / "app.override.yaml"
        override.write_text(
            "apiVersion: napt/v1\nparent: base.yaml\nname: Child\nid: child\n"
        )

        result = validate_recipe(override)

        assert result.is_valid
        assert result.warnings == []
        assert result.parent_path == str(parent.resolve())

    def test_recipe_without_parent_has_no_parent_path(self, tmp_path):
        """Tests that a plain recipe reports no parent."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert result.is_valid
        assert result.parent_path is None

    def test_parent_without_suffix_warns(self, tmp_path):
        """Tests that declaring parent in a file without the suffix warns."""
        self._write_parent(tmp_path)
        recipe = tmp_path / "app.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nparent: base.yaml\nname: Child\nid: child\n"
        )

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any("not named <app>.override.yaml" in w for w in result.warnings)

    def test_suffix_without_parent_warns(self, tmp_path):
        """Tests that the suffix on a file with no parent warns."""
        recipe = tmp_path / "app.override.yaml"
        recipe.write_text(_DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any("declares no parent" in w for w in result.warnings)

    def test_missing_parent_file_is_invalid(self, tmp_path):
        """Tests that a parent path that does not exist is an error."""
        recipe = tmp_path / "app.override.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nparent: missing.yaml\nname: Child\nid: child\n"
        )

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("Parent recipe not found" in err for err in result.errors)

    def test_parent_chain_is_invalid(self, tmp_path):
        """Tests that a parent declaring its own parent is an error."""
        self._write_parent(tmp_path, "parent: other.yaml\n" + _DEPLOYMENT_RECIPE_HEADER)
        recipe = tmp_path / "app.override.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nparent: base.yaml\nname: Child\nid: child\n"
        )

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("Parent chains are not supported" in err for err in result.errors)

    def test_non_string_parent_is_invalid(self, tmp_path):
        """Tests that a non-string parent value is an error."""
        recipe = tmp_path / "app.override.yaml"
        recipe.write_text("apiVersion: napt/v1\nparent: 5\nname: Child\nid: child\n")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("non-empty string" in err for err in result.errors)


_API_JSON_RECIPE = """
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: api_json
  api_url: "https://api.vendor.com/latest"
  version_path: "version"
  download_url_path: "download_url"
  headers:
    Authorization: "Bearer ${API_TOKEN}"
"""


def _write_org(tmp_path, body: str) -> None:
    """Writes defaults/org.yaml so the recipe under tmp_path picks it up."""
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "org.yaml").write_text("apiVersion: napt/v1\n" + body)


def _write_recipe(tmp_path, body: str, name: str = "app.yaml"):
    recipe = tmp_path / "recipes" / name
    recipe.parent.mkdir(parents=True, exist_ok=True)
    recipe.write_text(body)
    return recipe


class TestEffectiveConfigValidation:
    """Tests that validate_recipe checks the effective configuration."""

    def test_org_yaml_error_is_reported(self, tmp_path):
        """Tests that an invalid org.yaml value surfaces for the recipe."""
        _write_org(tmp_path, "intune:\n  build_types: sideways\n")
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("intune.build_types" in err for err in result.errors)

    def test_org_yaml_warning_is_reported(self, tmp_path):
        """Tests that an unknown org.yaml field warns for the recipe."""
        _write_org(tmp_path, "intune:\n  colour: blue\n")
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any("colour" in warning for warning in result.warnings)

    def test_result_carries_the_app_id(self, tmp_path):
        """Tests that the validated recipe's id is on the result."""
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        assert validate_recipe(recipe).app_id == "test-app"

    def test_broken_org_yaml_is_reported_not_raised(self, tmp_path):
        """Tests that org.yaml that cannot be parsed is an invalid result."""
        _write_org(tmp_path, "intune: [\n")
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("org.yaml" in err for err in result.errors)


class TestSecretsValidation:
    """Tests for the org.yaml secrets section and its use by recipes."""

    def test_header_secret_declared_for_the_host_is_valid(self, tmp_path):
        """Tests the happy path: org.yaml binds the variable to api_url's host."""
        _write_org(tmp_path, "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n")
        recipe = _write_recipe(tmp_path, _API_JSON_RECIPE)

        result = validate_recipe(recipe)

        assert result.errors == []
        assert result.is_valid

    def test_header_secret_without_declaration_is_invalid(self, tmp_path):
        """Tests that a header referencing an undeclared variable fails."""
        _write_org(tmp_path, "")
        recipe = _write_recipe(tmp_path, _API_JSON_RECIPE)

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any(
            "discovery.headers.Authorization" in err and "API_TOKEN" in err
            for err in result.errors
        )

    def test_header_secret_bound_to_another_host_is_invalid(self, tmp_path):
        """Tests that the binding check runs against the recipe's api_url."""
        _write_org(tmp_path, "secrets:\n  API_TOKEN:\n    hosts: [api.other.com]\n")
        recipe = _write_recipe(tmp_path, _API_JSON_RECIPE)

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("Refusing to send secret API_TOKEN" in err for err in result.errors)

    def test_secrets_declared_by_the_recipe_are_invalid(self, tmp_path):
        """Tests that a recipe cannot declare its own secrets."""
        _write_org(tmp_path, "")
        recipe = _write_recipe(
            tmp_path,
            _API_JSON_RECIPE + "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n",
        )

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any(
            "secrets.API_TOKEN" in err and "org.yaml" in err for err in result.errors
        )

    def test_secrets_declared_by_a_parent_are_invalid(self, tmp_path):
        """Tests that a parent recipe (an upstream file) cannot declare a
        secret or bind one to its own host."""
        _write_org(tmp_path, "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n")
        _write_recipe(
            tmp_path,
            _API_JSON_RECIPE.replace("api.vendor.com", "evil.example.com")
            + "secrets:\n  API_TOKEN:\n    hosts: [evil.example.com]\n"
            + "  OTHER:\n    hosts: [evil.example.com]\n",
            name="base.yaml",
        )
        child = _write_recipe(
            tmp_path,
            "apiVersion: napt/v1\nparent: base.yaml\nname: Child\nid: child\n",
            name="child.override.yaml",
        )

        result = validate_recipe(child)

        assert not result.is_valid
        assert any("secrets.API_TOKEN" in err for err in result.errors)
        assert any("secrets.OTHER" in err for err in result.errors)
        assert any("parent" in err for err in result.errors)
        # The parent's host list never reaches the binding check.
        assert any("Refusing to send secret API_TOKEN" in err for err in result.errors)

    def test_secrets_declared_by_a_vendor_file_are_invalid(self, tmp_path):
        """Tests that a vendor defaults file cannot declare secrets."""
        _write_org(tmp_path, "")
        vendors = tmp_path / "defaults" / "vendors"
        vendors.mkdir()
        (vendors / "Vendor.yaml").write_text(
            "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n"
        )
        recipe = _write_recipe(tmp_path, _API_JSON_RECIPE, name="Vendor/app.yaml")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any(
            "secrets.API_TOKEN" in err and "vendor" in err for err in result.errors
        )

    def test_secrets_overwritten_by_the_recipe_with_a_scalar_is_invalid(self, tmp_path):
        """Tests that a recipe replacing the whole section with a non-mapping
        is reported as the recipe's doing, not as a shape error alone."""
        _write_org(tmp_path, "")
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER + "secrets: 5\n")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any("secrets: declared in the recipe" in err for err in result.errors)

    @pytest.mark.parametrize(
        ("body", "fragment"),
        [
            ("secrets: 5\n", "secrets: Must be a dictionary"),
            ("secrets:\n", "secrets: Must be a dictionary"),
            ("secrets:\n  API_TOKEN: 5\n", "secrets.API_TOKEN: Must be a dictionary"),
            (
                "secrets:\n  API_TOKEN: {}\n",
                "secrets.API_TOKEN: Missing required field: hosts",
            ),
            (
                "secrets:\n  API_TOKEN:\n    hosts: []\n",
                "secrets.API_TOKEN: Missing required field: hosts",
            ),
            (
                "secrets:\n  API_TOKEN:\n    hosts: api.vendor.com\n",
                "secrets.API_TOKEN.hosts: Must be list",
            ),
            (
                "secrets:\n  API_TOKEN:\n    hosts: [https://api.vendor.com/x]\n",
                "secrets.API_TOKEN.hosts[0]: Must be a hostname",
            ),
            (
                "secrets:\n  API_TOKEN:\n    hosts: ['']\n",
                "secrets.API_TOKEN.hosts[0]: Must be a hostname",
            ),
            (
                "secrets:\n  not a name:\n    hosts: [api.vendor.com]\n",
                "secrets: 'not a name' is not an environment variable name",
            ),
        ],
    )
    def test_malformed_secrets_section(self, tmp_path, body, fragment):
        """Tests that a malformed secrets section is reported by path."""
        _write_org(tmp_path, body)
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert any(fragment in err for err in result.errors), result.errors

    def test_unknown_secret_entry_field_warns(self, tmp_path):
        """Tests that a misspelled entry field is a warning."""
        _write_org(
            tmp_path,
            "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n    host: x\n",
        )
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any(
            "secrets.API_TOKEN: Unknown field 'host'" in w for w in result.warnings
        )


class TestValidateRecipes:
    """Tests for validating a recipe file or a directory of recipes."""

    def test_file_returns_one_result(self, tmp_path):
        """Tests that a single file validates as before."""
        recipe = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER)

        results = validate_recipes(recipe)

        assert [r.is_valid for r in results] == [True]
        assert results[0].recipe_path == str(recipe)

    def test_directory_validates_every_recipe(self, tmp_path):
        """Tests that each recipe under the directory gets its own result."""
        _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER, name="a/one.yaml")
        _write_recipe(
            tmp_path, "apiVersion: napt/v1\nname: Two\nid: two\n", name="b/two.yml"
        )

        results = validate_recipes(tmp_path / "recipes")

        assert [r.is_valid for r in results] == [True, False]
        assert results[0].recipe_path.endswith("one.yaml")
        assert any("discovery" in err for err in results[1].errors)

    def test_duplicate_ids_are_reported_on_the_second_file(self, tmp_path):
        """Tests that two recipes resolving to one id are both named."""
        parent = _write_recipe(tmp_path, _DEPLOYMENT_RECIPE_HEADER, name="base.yaml")
        child = _write_recipe(
            tmp_path,
            "apiVersion: napt/v1\nparent: base.yaml\n",
            name="base.override.yaml",
        )

        results = validate_recipes(tmp_path / "recipes")

        assert [r.is_valid for r in results].count(False) == 1
        dup = next(r for r in results if not r.is_valid)
        assert any(
            "test-app" in err and parent.name in err and child.name in err
            for err in dup.errors
        )

    def test_missing_path_is_a_single_invalid_result(self, tmp_path):
        """Tests that a path that does not exist is reported, not raised."""
        results = validate_recipes(tmp_path / "nope")

        assert len(results) == 1
        assert not results[0].is_valid

    def test_empty_directory_is_a_single_invalid_result(self, tmp_path):
        """Tests that a directory with no recipes is reported, not raised."""
        (tmp_path / "recipes").mkdir()

        results = validate_recipes(tmp_path / "recipes")

        assert len(results) == 1
        assert not results[0].is_valid
        assert any("No recipe files" in err for err in results[0].errors)


_BASE = """
apiVersion: napt/v1
name: "Test App"
id: "test-app"
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
"""


def _validate(tmp_path, body: str):
    """Validates a recipe made of the minimal header plus ``body``."""
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(_BASE + body)
    return validate_recipe(recipe)


class TestIntegerFields:
    """Tests that integer fields reject booleans and out-of-range values."""

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            (
                "intune:\n  max_run_time_minutes: true\n",
                "intune.max_run_time_minutes",
            ),
            ("logging:\n  log_rotation_mb: false\n", "logging.log_rotation_mb"),
            (
                "deployment:\n  retain_versions: true\n",
                "deployment.retain_versions",
            ),
        ],
    )
    def test_bool_is_not_an_integer(self, tmp_path, body, field):
        """Tests that a YAML boolean does not pass as an integer."""
        result = _validate(tmp_path, body)

        assert not result.is_valid
        assert any(
            err.startswith(f"{field}: Must be int, got bool") for err in result.errors
        )

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (
                "intune:\n  max_run_time_minutes: 0\n",
                "intune.max_run_time_minutes: Must be between 1 and 1440",
            ),
            (
                "intune:\n  max_run_time_minutes: 1441\n",
                "intune.max_run_time_minutes: Must be between 1 and 1440",
            ),
            (
                "logging:\n  log_rotation_mb: 0\n",
                "logging.log_rotation_mb: Must be >= 1",
            ),
            (
                "deployment:\n  retain_versions: -1\n",
                "deployment.retain_versions: Must be >= 0",
            ),
        ],
    )
    def test_out_of_range_integer_is_an_error(self, tmp_path, body, message):
        """Tests that an integer outside its documented range is reported."""
        result = _validate(tmp_path, body)

        assert not result.is_valid
        assert any(err.startswith(message) for err in result.errors)

    @pytest.mark.parametrize(
        "body",
        [
            "intune:\n  max_run_time_minutes: 1\n",
            "intune:\n  max_run_time_minutes: 1440\n",
            "logging:\n  log_rotation_mb: 1\n",
            "deployment:\n  retain_versions: 0\n",
        ],
    )
    def test_boundary_values_are_valid(self, tmp_path, body):
        """Tests that the documented limits themselves pass."""
        result = _validate(tmp_path, body)

        assert result.is_valid
        assert result.errors == []

    def test_ring_promote_after_days_lower_bound(self, tmp_path):
        """Tests that a negative promote_after_days is reported by its path."""
        result = _validate(
            tmp_path,
            "deployment:\n  rings:\n    - name: pilot\n      groups: [g]\n"
            "      promote_after_days: -1\n",
        )

        assert not result.is_valid
        assert any(
            err.startswith("deployment.rings[0].promote_after_days: Must be >= 0")
            for err in result.errors
        )


class TestPsadtSchema:
    """Tests for the psadt: section schema (types, brand pack, unknown keys)."""

    def test_float_release_is_an_error(self, tmp_path):
        """Tests that an unquoted release such as 4.1 (a YAML float) is rejected."""
        result = _validate(tmp_path, "psadt:\n  release: 4.1\n")

        assert not result.is_valid
        assert any(
            err.startswith("psadt.release: Must be str, got float")
            for err in result.errors
        )

    def test_unknown_field_warns_with_hint(self, tmp_path):
        """Tests that a misspelled psadt key is reported with the closest known key."""
        result = _validate(tmp_path, "psadt:\n  relaese: latest\n")

        assert result.is_valid
        assert (
            "psadt: Unknown field 'relaese'. Did you mean 'release'?" in result.warnings
        )

    def test_removed_psadt_cache_dir_warns(self, tmp_path):
        """Tests that the removed psadt.cache_dir key is reported as unknown."""
        result = _validate(tmp_path, "psadt:\n  cache_dir: cache/psadt\n")

        assert result.is_valid
        assert any(
            w.startswith("psadt: Unknown field 'cache_dir'") for w in result.warnings
        )

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("psadt:\n  brand_pack: x\n", "psadt.brand_pack: Must be a dictionary"),
            ("psadt:\n  brand_pack:\n", "psadt.brand_pack: Must be a dictionary"),
            (
                "psadt:\n  brand_pack:\n    path: brand\n    mappings: x\n",
                "psadt.brand_pack.mappings: Must be list, got str",
            ),
            (
                'psadt:\n  brand_pack:\n    path: brand\n    mappings: ["AppIcon.*"]\n',
                "psadt.brand_pack.mappings[0]: Must be a dictionary",
            ),
            (
                "psadt:\n  brand_pack:\n    path: brand\n    mappings:\n"
                '      - source: "AppIcon.*"\n',
                "psadt.brand_pack.mappings[0]: Missing required field: target",
            ),
            (
                "psadt:\n  brand_pack:\n    path: brand\n    mappings:\n"
                '      - source: ""\n        target: Assets/AppIcon\n',
                "psadt.brand_pack.mappings[0]: Missing required field: source",
            ),
            (
                "psadt:\n  brand_pack:\n    path: 5\n    mappings: []\n",
                "psadt.brand_pack.path: Must be str, got int",
            ),
        ],
    )
    def test_brand_pack_shape_is_checked(self, tmp_path, body, message):
        """Tests that a malformed brand pack is a validation error, not a crash."""
        result = _validate(tmp_path, body)

        assert not result.is_valid
        assert any(err.startswith(message) for err in result.errors)

    def test_brand_pack_mapping_unknown_field_warns(self, tmp_path):
        """Tests that an unknown key in a mapping is reported by its indexed path."""
        result = _validate(
            tmp_path,
            "psadt:\n  brand_pack:\n    path: brand\n    mappings:\n"
            '      - source: "AppIcon.*"\n        target: Assets/AppIcon\n'
            "        dest: x\n",
        )

        assert result.is_valid
        assert any(
            w.startswith("psadt.brand_pack.mappings[0]: Unknown field 'dest'")
            for w in result.warnings
        )

    @pytest.mark.parametrize(
        "target",
        [
            "../../Invoke-AppDeployToolkit.ps1",
            "C:/Windows/x",
            "/etc/x",
            "Assets\\AppIcon",
            "Assets/",
        ],
    )
    def test_brand_pack_target_must_stay_inside_the_build(self, tmp_path, target):
        """Tests that a mapping target cannot name a path outside the build folder."""
        result = _validate(
            tmp_path,
            "psadt:\n  brand_pack:\n    path: brand\n    mappings:\n"
            f"      - source: 'AppIcon.*'\n        target: '{target}'\n",
        )

        assert not result.is_valid
        assert any(
            err.startswith(
                "psadt.brand_pack.mappings[0].target: Must be a relative path"
            )
            for err in result.errors
        )

    def test_valid_brand_pack_passes(self, tmp_path):
        """Tests that a well-formed brand pack produces no errors or warnings."""
        result = _validate(
            tmp_path,
            "psadt:\n  brand_pack:\n    path: brand\n    mappings:\n"
            '      - source: "AppIcon.*"\n        target: Assets/AppIcon\n',
        )

        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []

    def test_install_must_be_a_string(self, tmp_path):
        """Tests that a non-string install block is rejected."""
        result = _validate(tmp_path, "psadt:\n  install: [a, b]\n")

        assert not result.is_valid
        assert any(
            err.startswith("psadt.install: Must be str, got list")
            for err in result.errors
        )


class TestToolSections:
    """Tests for the directories: and intunewin: sections."""

    def test_directories_unknown_key_warns_with_hint(self, tmp_path):
        """Tests that a misspelled directory key names the key it is closest to."""
        result = _validate(tmp_path, "directories:\n  packages: out\n")

        assert result.is_valid
        assert (
            "directories: Unknown field 'packages'. Did you mean 'package'?"
            in result.warnings
        )

    def test_cache_directory_key_is_known(self, tmp_path):
        """Tests that directories.cache is accepted without a warning."""
        result = _validate(tmp_path, "directories:\n  cache: .napt-cache\n")

        assert result.is_valid
        assert not any("directories" in w for w in result.warnings)

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (
                "directories:\n  discover: 5\n",
                "directories.discover: Must be str, got int",
            ),
            ("directories:\n", "directories: Must be a dictionary"),
            ("directories: x\n", "directories: Must be a dictionary"),
            (
                "intunewin:\n  release: 1.8\n",
                "intunewin.release: Must be str, got float",
            ),
            ("intunewin:\n", "intunewin: Must be a dictionary"),
        ],
    )
    def test_tool_section_types(self, tmp_path, body, message):
        """Tests that the tool sections are type-checked like the others."""
        result = _validate(tmp_path, body)

        assert not result.is_valid
        assert any(err.startswith(message) for err in result.errors)

    def test_intunewin_unknown_key_warns(self, tmp_path):
        """Tests that an unknown intunewin key is reported."""
        result = _validate(tmp_path, "intunewin:\n  version: latest\n")

        assert result.is_valid
        assert any(
            w.startswith("intunewin: Unknown field 'version'") for w in result.warnings
        )


class TestTopLevelKeys:
    """Tests for unknown keys at the top of a recipe."""

    def test_unknown_top_level_key_warns_with_hint(self, tmp_path):
        """Tests that a miscased section name is reported with the right one."""
        result = _validate(tmp_path, "inTune:\n  is_featured: true\n")

        assert result.is_valid
        assert "Unknown field 'inTune'. Did you mean 'intune'?" in result.warnings

    def test_unknown_top_level_key_without_a_match(self, tmp_path):
        """Tests that a key unlike any section is still reported."""
        result = _validate(tmp_path, "notes: hello\n")

        assert result.is_valid
        assert "Unknown field 'notes'" in result.warnings

    def test_provenance_is_not_reported(self, tmp_path):
        """Tests that the loader's own provenance entry is never an unknown key."""
        result = _validate(tmp_path, "")

        assert result.warnings == []

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("1: x\n", "Key 1 must be a string"),
            ("intune:\n  ~: x\n", "intune: Key None must be a string"),
            (
                "discovery:\n  strategy: url_download\n  url: https://x\n  2: y\n",
                "discovery: Key 2 must be a string",
            ),
        ],
    )
    def test_non_string_key_is_an_error(self, tmp_path, body, message):
        """Tests that a YAML key that is not a string is reported, not crashed on."""
        result = _validate(tmp_path, body)

        assert not result.is_valid
        assert message in result.errors


class TestDiscoveryKeys:
    """Tests for unknown keys under discovery, per strategy."""

    def test_api_github_unknown_key_warns_with_hint(self, tmp_path):
        """Tests that a misspelled strategy field is reported with the missing one."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Git"
id: "git"
discovery:
  strategy: api_github
  repos: "git/git"
  asset_pattern: ".*\\\\.exe$"
""")

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert "discovery: Missing required field: repo" in result.errors
        assert (
            "discovery: Unknown field 'repos'. Did you mean 'repo'?" in result.warnings
        )

    def test_prerelease_is_no_longer_a_field(self, tmp_path):
        """Tests that the removed prerelease field is reported as unknown."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("""
apiVersion: napt/v1
name: "Git"
id: "git"
discovery:
  strategy: api_github
  repo: "git/git"
  asset_pattern: ".*\\\\.exe$"
  prerelease: false
""")

        result = validate_recipe(recipe)

        assert result.is_valid
        assert any(
            w.startswith("discovery: Unknown field 'prerelease'")
            for w in result.warnings
        )

    @pytest.mark.parametrize(
        ("strategy_body", "unknown"),
        [
            (
                "strategy: url_download\n  url: https://x/a.msi\n  version_patern: x\n",
                "version_patern",
            ),
            (
                "strategy: api_json\n  api_url: https://x\n  version_path: v\n"
                "  download_url_path: d\n  header: {}\n",
                "header",
            ),
            (
                "strategy: web_scrape\n  page_url: https://x\n  link_pattern: a\n"
                "  version_pattern: b\n  versionformat: c\n",
                "versionformat",
            ),
        ],
    )
    def test_every_strategy_reports_unknown_keys(
        self, tmp_path, strategy_body, unknown
    ):
        """Tests that each strategy's field list drives the unknown-key check."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: A\nid: a\ndiscovery:\n  " + strategy_body
        )

        result = validate_recipe(recipe)

        assert any(
            f"discovery: Unknown field '{unknown}'" in w for w in result.warnings
        )

    def test_unknown_strategy_skips_the_key_check(self, tmp_path):
        """Tests that an unregistered strategy reports only the strategy error."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: A\nid: a\ndiscovery:\n"
            "  strategy: ftp\n  host: x\n"
        )

        result = validate_recipe(recipe)

        assert not result.is_valid
        assert result.warnings == []


class TestTypoHints:
    """Tests that the closest-key hint is deterministic and not over-eager."""

    def test_hint_is_the_closest_field(self, tmp_path):
        """Tests that a key near two fields gets the closer one, not either."""
        result = _validate(tmp_path, "intune:\n  command: x\n")

        assert [w for w in result.warnings if "command" in w] == [
            "intune: Unknown field 'command'. Did you mean 'install_command'?"
        ]

    def test_short_key_gets_no_far_fetched_hint(self, tmp_path):
        """Tests that a key sharing a few letters with a field is not matched."""
        result = _validate(tmp_path, "intune:\n  name: x\n")

        assert "intune: Unknown field 'name'" in result.warnings
