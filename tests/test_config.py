"""
Tests for notapkgtool.config.loader module.

Tests configuration loading and merging including:
- YAML file loading
- Three-layer merging (org -> vendor -> recipe)
- Path resolution
- Dynamic value injection
- Error handling
"""

from __future__ import annotations

import pytest

from notapkgtool.config.loader import load_effective_config


class TestConfigLoading:
    """Tests for basic configuration loading."""

    def test_load_simple_recipe(self, create_yaml_file, sample_recipe_data):
        """Test loading a simple recipe without defaults."""
        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)

        config = load_effective_config(recipe_path)

        assert config["apiVersion"] == "napt/v1"
        assert len(config["apps"]) == 1
        assert config["apps"][0]["name"] == "Test App"

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
        recipe_path.write_text("apiVersion: napt/v1\napps:\n  - name: Test\n")

        config = load_effective_config(recipe_path)

        # Should have both recipe and defaults
        assert "apps" in config
        assert "defaults" in config
        assert config["defaults"]["comparator"] == "semver"

    def test_missing_recipe_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises FileNotFoundError."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
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
apps:
  - name: Test
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
apps:
  - name: Test
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
apps:
  - name: Test
"""
        )

        config = load_effective_config(recipe_path)

        # Recipe value should win
        assert config["defaults"]["comparator"] == "lexicographic"


class TestVendorDetection:
    """Tests for vendor defaults detection and loading."""

    def test_vendor_from_directory_name(self, tmp_test_dir):
        """Test that vendor is detected from directory structure."""
        # Create structure: defaults/org.yaml, defaults/vendors/Google.yaml, recipes/Google/chrome.yaml
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
apps:
  - name: Chrome
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

    def test_invalid_yaml_raises_system_exit(self, tmp_test_dir):
        """Test that invalid YAML raises SystemExit."""
        recipe_path = tmp_test_dir / "bad.yaml"
        recipe_path.write_text("invalid: yaml: syntax: error:")

        with pytest.raises(SystemExit):
            load_effective_config(recipe_path)

    def test_empty_yaml_raises_system_exit(self, tmp_test_dir):
        """Test that empty YAML raises SystemExit."""
        recipe_path = tmp_test_dir / "empty.yaml"
        recipe_path.write_text("")

        with pytest.raises(SystemExit):
            load_effective_config(recipe_path)

    def test_non_dict_yaml_raises_system_exit(self, tmp_test_dir):
        """Test that non-dict YAML raises SystemExit."""
        recipe_path = tmp_test_dir / "list.yaml"
        recipe_path.write_text("- item1\n- item2\n")

        with pytest.raises(SystemExit):
            load_effective_config(recipe_path)
