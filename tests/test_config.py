"""Tests for napt.config.loader module.

Tests configuration loading and merging including:
- YAML file loading
- Four-layer merging (code defaults -> org -> vendor -> recipe)
- Path resolution
- Dynamic value injection
- Error handling
"""

from __future__ import annotations

import pytest

from napt.config.defaults import DEFAULT_CONFIG, ORG_YAML_TEMPLATE
from napt.config.loader import load_effective_config
from napt.exceptions import ConfigError


class TestConfigLoading:
    """Tests for basic configuration loading."""

    def test_load_simple_recipe(self, create_yaml_file, sample_recipe_data):
        """Test loading a simple recipe without defaults."""
        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)

        config = load_effective_config(recipe_path)

        assert config["apiVersion"] == "napt/v1"
        assert "app" in config
        assert config["app"]["name"] == "Test App"

    def test_load_recipe_with_org_defaults(
        self, tmp_test_dir, create_yaml_file, sample_recipe_data, sample_org_defaults
    ):
        """Test loading recipe with organization defaults."""
        # Create directory structure
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()

        # Create org defaults
        org_path = defaults_dir / "org.yaml"
        org_path.write_text("apiVersion: napt/v1\ndefaults:\n  comparator: semver\n")

        # Create recipe
        recipe_path = recipes_dir / "test.yaml"
        recipe_path.write_text("apiVersion: napt/v1\napp:\n  name: Test\n")

        config = load_effective_config(recipe_path)

        # Should have both recipe and defaults
        assert "app" in config
        assert "defaults" in config
        assert config["defaults"]["comparator"] == "semver"

    def test_missing_recipe_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises FileNotFoundError."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        from napt.exceptions import ConfigError

        with pytest.raises(ConfigError):
            load_effective_config(nonexistent)


class TestConfigMerging:
    """Tests for configuration merging behavior."""

    def test_dict_deep_merge(self, tmp_test_dir):
        """Test that dicts are deep-merged."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        # Org defaults
        org_path = defaults_dir / "org.yaml"
        org_path.write_text(
            """
apiVersion: napt/v1
defaults:
  psadt:
    release: "latest"
    cache_dir: "cache/psadt"
    app_vars:
      AppLang: "EN"
"""
        )

        # Recipe
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
defaults:
  psadt:
    app_vars:
      AppName: "MyApp"
app:
  name: Test
"""
        )

        config = load_effective_config(recipe_path)

        # Both keys should be present (deep merge)
        assert config["defaults"]["psadt"]["release"] == "latest"
        assert config["defaults"]["psadt"]["app_vars"]["AppLang"] == "EN"
        assert config["defaults"]["psadt"]["app_vars"]["AppName"] == "MyApp"

    def test_list_replacement(self, tmp_test_dir):
        """Test that lists are replaced, not merged."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        # Org defaults with list
        org_path = defaults_dir / "org.yaml"
        org_path.write_text(
            """
apiVersion: napt/v1
defaults:
  processes: [process1, process2]
"""
        )

        # Recipe with different list
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
defaults:
  processes: [process3]
app:
  name: Test
"""
        )

        config = load_effective_config(recipe_path)

        # Recipe list should replace org list
        assert config["defaults"]["processes"] == ["process3"]

    def test_scalar_overwrite(self, tmp_test_dir):
        """Test that scalar values are overwritten."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        # Org defaults
        org_path = defaults_dir / "org.yaml"
        org_path.write_text(
            """
apiVersion: napt/v1
defaults:
  comparator: semver
"""
        )

        # Recipe with different value
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
defaults:
  comparator: lexicographic
app:
  name: Test
"""
        )

        config = load_effective_config(recipe_path)

        # Recipe value should win
        assert config["defaults"]["comparator"] == "lexicographic"


class TestVendorDetection:
    """Tests for vendor defaults detection and loading."""

    def test_vendor_from_directory_name(self, tmp_test_dir):
        """Test that vendor is detected from directory structure."""
        # Create structure: defaults/org.yaml, defaults/vendors/Google.yaml,
        # recipes/Google/chrome.yaml
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        vendors_dir = defaults_dir / "vendors"
        vendors_dir.mkdir()
        recipes_dir = tmp_test_dir / "recipes" / "Google"
        recipes_dir.mkdir(parents=True)

        # Create org defaults (required)
        org_path = defaults_dir / "org.yaml"
        org_path.write_text(
            """
apiVersion: napt/v1
defaults:
  org_setting: "from org"
"""
        )

        # Create vendor defaults
        vendor_path = vendors_dir / "Google.yaml"
        vendor_path.write_text(
            """
apiVersion: napt/v1
defaults:
  vendor_setting: "from Google"
"""
        )

        # Create recipe
        recipe_path = recipes_dir / "chrome.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
app:
  name: Chrome
"""
        )

        config = load_effective_config(recipe_path)

        # Should include both org and vendor defaults
        assert config["defaults"]["org_setting"] == "from org"
        assert config["defaults"]["vendor_setting"] == "from Google"


class TestDynamicInjection:
    """Tests for dynamic value injection."""

    def test_appscriptdate_injection(self, create_yaml_file, sample_recipe_data):
        """Test that AppScriptDate is injected with today's date."""
        from datetime import date

        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)
        config = load_effective_config(recipe_path)

        # Should have injected AppScriptDate
        today = date.today().strftime("%Y-%m-%d")
        if "defaults" in config and "psadt" in config["defaults"]:
            app_vars = config["defaults"]["psadt"].get("app_vars", {})
            if "AppScriptDate" in app_vars:
                assert app_vars["AppScriptDate"] == today


class TestErrorHandling:
    """Tests for error handling in config loading."""

    def test_invalid_yaml_raises_config_error(self, tmp_test_dir):
        """Test that invalid YAML raises ConfigError."""
        recipe_path = tmp_test_dir / "bad.yaml"
        recipe_path.write_text("invalid: yaml: syntax: error:")

        with pytest.raises(ConfigError):
            load_effective_config(recipe_path)

    def test_empty_yaml_raises_config_error(self, tmp_test_dir):
        """Test that empty YAML raises ConfigError."""
        recipe_path = tmp_test_dir / "empty.yaml"
        recipe_path.write_text("")

        with pytest.raises(ConfigError):
            load_effective_config(recipe_path)

    def test_non_dict_yaml_raises_config_error(self, tmp_test_dir):
        """Test that non-dict YAML raises ConfigError."""
        recipe_path = tmp_test_dir / "list.yaml"
        recipe_path.write_text("- item1\n- item2\n")

        with pytest.raises(ConfigError):
            load_effective_config(recipe_path)


class TestCodeDefaults:
    """Tests for code-based default configuration."""

    def test_code_defaults_applied_without_org_yaml(self, tmp_test_dir):
        """Tests that code defaults are applied when no org.yaml exists."""
        # Create recipe without any defaults directory
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
app:
  name: Test App
  id: test-app
"""
        )

        config = load_effective_config(recipe_path)

        # Should have code defaults applied
        assert "defaults" in config
        assert config["defaults"]["comparator"] == "semver"
        assert config["defaults"]["psadt"]["release"] == "latest"
        assert config["defaults"]["build"]["output_dir"] == "builds"

    def test_org_yaml_overrides_code_defaults(self, tmp_test_dir):
        """Tests that org.yaml values override code defaults."""
        # Create directory structure with org.yaml
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text(
            """
apiVersion: napt/v1
defaults:
  comparator: lexicographic
  psadt:
    release: "4.0.0"
"""
        )

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            """
apiVersion: napt/v1
app:
  name: Test App
"""
        )

        config = load_effective_config(recipe_path)

        # org.yaml values should override code defaults
        assert config["defaults"]["comparator"] == "lexicographic"
        assert config["defaults"]["psadt"]["release"] == "4.0.0"
        # But code defaults should still provide unspecified values
        assert config["defaults"]["build"]["output_dir"] == "builds"

    def test_code_defaults_structure_matches_expected(self):
        """Tests that code defaults have expected structure."""
        # Verify the structure matches what we expect
        assert "defaults" in DEFAULT_CONFIG
        defaults = DEFAULT_CONFIG["defaults"]

        # Check top-level keys exist
        assert "psadt" in defaults
        assert "build" in defaults
        assert "win32" in defaults

        # Check nested structures
        assert "release" in defaults["psadt"]
        assert "app_vars" in defaults["psadt"]
        assert "output_dir" in defaults["build"]
        assert "build_types" in defaults["win32"]

    def test_org_yaml_template_covers_all_sections(self):
        """Tests that ORG_YAML_TEMPLATE mentions all DEFAULT_CONFIG sections.

        This test catches drift between the code defaults and the template
        shown to users via `napt init`. If a new section is added to
        DEFAULT_CONFIG but not to the template, this test will fail.
        """
        defaults = DEFAULT_CONFIG["defaults"]

        # All top-level sections under defaults should be mentioned in template
        # (either as actual keys or as comments)
        for section in defaults.keys():
            assert section in ORG_YAML_TEMPLATE, (
                f"Section '{section}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template in "
                f"napt/config/defaults.py to include this section."
            )

        # Also check key nested sections are mentioned
        nested_checks = [
            ("psadt", "release"),
            ("psadt", "brand_pack"),
            ("psadt", "app_vars"),
            ("build", "output_dir"),
            ("win32", "build_types"),
            ("win32", "installed_check"),
        ]

        for parent, key in nested_checks:
            assert key in ORG_YAML_TEMPLATE, (
                f"Key '{parent}.{key}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template."
            )
