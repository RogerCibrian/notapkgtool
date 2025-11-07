"""
Tests for recipe validation module.

This module tests the validation functionality that checks recipe syntax
and configuration without making network calls or downloading files.
"""

from __future__ import annotations

from notapkgtool.validation import ValidationError, validate_recipe


class TestValidateRecipe:
    """Tests for validate_recipe function."""

    def test_valid_recipe_http_static(self, tmp_path):
        """Test that a valid http_static recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test App"
    id: "test-app"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "valid"
        assert result["app_count"] == 1
        assert len(result["errors"]) == 0
        assert len(result["warnings"]) == 0

    def test_valid_recipe_github_release(self, tmp_path):
        """Test that a valid github_release recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Git"
    id: "git"
    source:
      strategy: github_release
      repo: "git/git"
      asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "valid"
        assert result["app_count"] == 1
        assert len(result["errors"]) == 0

    def test_valid_recipe_url_regex(self, tmp_path):
        """Test that a valid url_regex recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test App"
    id: "test-app"
    source:
      strategy: url_regex
      url: "https://example.com/app-v1.2.3.msi"
      pattern: "app-v(?P<version>[0-9.]+)\\\\.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "valid"
        assert result["app_count"] == 1
        assert len(result["errors"]) == 0

    def test_valid_recipe_http_json(self, tmp_path):
        """Test that a valid http_json recipe passes validation."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test App"
    id: "test-app"
    source:
      strategy: http_json
      api_url: "https://api.example.com/latest"
      version_path: "version"
      download_url_path: "download_url"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "valid"
        assert result["app_count"] == 1
        assert len(result["errors"]) == 0

    def test_missing_file(self, tmp_path):
        """Test that missing recipe file is reported."""
        recipe = tmp_path / "nonexistent.yaml"

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]

    def test_invalid_yaml_syntax(self, tmp_path):
        """Test that invalid YAML syntax is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    invalid yaml: [unclosed bracket
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert len(result["errors"]) == 1
        assert "YAML syntax" in result["errors"][0]

    def test_empty_file(self, tmp_path):
        """Test that empty YAML file is handled."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("")

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert len(result["errors"]) >= 1

    def test_non_dict_yaml(self, tmp_path):
        """Test that non-dictionary YAML is rejected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("- item1\n- item2\n")

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("dictionary" in err.lower() for err in result["errors"])

    def test_missing_api_version(self, tmp_path):
        """Test that missing apiVersion is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("apiVersion" in err for err in result["errors"])

    def test_unsupported_api_version_warning(self, tmp_path):
        """Test that unsupported apiVersion generates warning."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v99
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert len(result["warnings"]) >= 1
        assert any("napt/v99" in warn for warn in result["warnings"])

    def test_missing_apps(self, tmp_path):
        """Test that missing apps field is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("apps" in err for err in result["errors"])

    def test_apps_not_list(self, tmp_path):
        """Test that apps must be a list."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps: "not a list"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("list" in err for err in result["errors"])

    def test_empty_apps_list(self, tmp_path):
        """Test that empty apps list is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps: []
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("at least one app" in err for err in result["errors"])

    def test_missing_app_name(self, tmp_path):
        """Test that missing app name is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("name" in err for err in result["errors"])

    def test_missing_app_id(self, tmp_path):
        """Test that missing app id is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("id" in err for err in result["errors"])

    def test_missing_source(self, tmp_path):
        """Test that missing source is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("source" in err for err in result["errors"])

    def test_missing_strategy(self, tmp_path):
        """Test that missing strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("strategy" in err for err in result["errors"])

    def test_unknown_strategy(self, tmp_path):
        """Test that unknown strategy is detected."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: nonexistent_strategy
      url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("Unknown" in err or "nonexistent" in err for err in result["errors"])

    def test_http_static_missing_url(self, tmp_path):
        """Test that http_static validates missing url."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("url" in err for err in result["errors"])

    def test_http_static_missing_version_type(self, tmp_path):
        """Test that http_static validates missing version type."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("version" in err for err in result["errors"])

    def test_github_release_missing_repo(self, tmp_path):
        """Test that github_release validates missing repo."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: github_release
      asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("repo" in err for err in result["errors"])

    def test_github_release_invalid_repo_format(self, tmp_path):
        """Test that github_release validates repo format."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: github_release
      repo: "invalid-repo-format"
      asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("owner/repo" in err or "format" in err for err in result["errors"])

    def test_url_regex_missing_pattern(self, tmp_path):
        """Test that url_regex validates missing pattern."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: url_regex
      url: "https://example.com/app-v1.2.3.msi"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any("pattern" in err for err in result["errors"])

    def test_url_regex_invalid_pattern(self, tmp_path):
        """Test that url_regex validates regex syntax."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: url_regex
      url: "https://example.com/app.msi"
      pattern: "[unclosed bracket"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert any(
            "regex" in err.lower() or "pattern" in err for err in result["errors"]
        )

    def test_http_json_missing_fields(self, tmp_path):
        """Test that http_json validates missing required fields."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_json
      api_url: "https://api.example.com/latest"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        # Should be missing version_path and download_url_path
        assert len(result["errors"]) >= 2

    def test_multiple_apps_all_valid(self, tmp_path):
        """Test validation with multiple valid apps."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "App1"
    id: "app1"
    source:
      strategy: http_static
      url: "https://example.com/app1.msi"
      version:
        type: msi_product_version_from_file
  - name: "App2"
    id: "app2"
    source:
      strategy: github_release
      repo: "owner/repo"
      asset_pattern: ".*\\\\.exe$"
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "valid"
        assert result["app_count"] == 2
        assert len(result["errors"]) == 0

    def test_multiple_apps_one_invalid(self, tmp_path):
        """Test that validation catches errors in any app."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Valid App"
    id: "app1"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
  - name: "Invalid App"
    id: "app2"
    source:
      strategy: http_static
      # Missing url
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert result["status"] == "invalid"
        assert result["app_count"] == 2
        assert len(result["errors"]) >= 1
        assert any("apps[1]" in err for err in result["errors"])

    def test_verbose_mode(self, tmp_path, capsys):
        """Test that verbose mode prints progress."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe, verbose=True)
        captured = capsys.readouterr()

        assert result["status"] == "valid"
        assert "Validating recipe" in captured.out
        assert "YAML syntax is valid" in captured.out
        assert "http_static" in captured.out

    def test_result_contains_recipe_path(self, tmp_path):
        """Test that result includes the recipe path."""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            """
apiVersion: napt/v1
apps:
  - name: "Test"
    id: "test"
    source:
      strategy: http_static
      url: "https://example.com/app.msi"
      version:
        type: msi_product_version_from_file
"""
        )

        result = validate_recipe(recipe)

        assert "recipe_path" in result
        assert str(recipe) in result["recipe_path"]


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_creation(self):
        """Test that ValidationError can be created."""
        error = ValidationError("Test error message")
        assert str(error) == "Test error message"

    def test_validation_error_is_exception(self):
        """Test that ValidationError is an Exception."""
        assert issubclass(ValidationError, Exception)
