"""Tests for napt.config.loader module.

Tests configuration loading and merging including:
- YAML file loading
- Four-layer merging (code defaults -> org -> vendor -> recipe)
- Path resolution
- Dynamic value injection
- Error handling
"""

from __future__ import annotations

from typing import Any

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
        assert config["name"] == "Test App"
        assert config["id"] == "test-app"

    def test_load_recipe_with_org_defaults(self, tmp_test_dir, create_yaml_file):
        """Test loading recipe with organization defaults."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("apiVersion: napt/v1\npsadt:\n  release: '4.0.0'\n")

        recipe_path = recipes_dir / "test.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nname: Test\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
        )

        config = load_effective_config(recipe_path)

        assert config["psadt"]["release"] == "4.0.0"

    def test_missing_recipe_file_raises(self, tmp_test_dir):
        """Test that missing recipe file raises FileNotFoundError."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(ConfigError):
            load_effective_config(nonexistent)


class TestConfigMerging:
    """Tests for configuration merging behavior."""

    def test_dict_deep_merge(self, tmp_test_dir):
        """Test that dicts are deep-merged."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  release: "latest"
  cache_dir: "cache/psadt"
  app_vars:
    AppLang: "EN"
""")

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Test
id: test
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
psadt:
  app_vars:
    AppName: "MyApp"
""")

        config = load_effective_config(recipe_path)

        # Both keys should be present (deep merge)
        assert config["psadt"]["release"] == "latest"
        assert config["psadt"]["app_vars"]["AppLang"] == "EN"
        assert config["psadt"]["app_vars"]["AppName"] == "MyApp"

    def test_list_replacement(self, tmp_test_dir):
        """Test that lists are replaced, not merged."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  app_vars:
    AppSuccessExitCodes: [0, 1707]
""")

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Test
id: test
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
psadt:
  app_vars:
    AppSuccessExitCodes: [0]
""")

        config = load_effective_config(recipe_path)

        # Recipe list should replace org list
        assert config["psadt"]["app_vars"]["AppSuccessExitCodes"] == [0]

    def test_scalar_overwrite(self, tmp_test_dir):
        """Test that scalar values are overwritten."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  release: "latest"
""")

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Test
id: test
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
psadt:
  release: "4.0.0"
""")

        config = load_effective_config(recipe_path)

        # Recipe value should win
        assert config["psadt"]["release"] == "4.0.0"


class TestVendorDetection:
    """Tests for vendor defaults detection and loading."""

    def test_vendor_from_directory_name(self, tmp_test_dir):
        """Test that vendor is detected from directory structure."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        vendors_dir = defaults_dir / "vendors"
        vendors_dir.mkdir()
        recipes_dir = tmp_test_dir / "recipes" / "Google"
        recipes_dir.mkdir(parents=True)

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  release: "latest"
""")

        vendor_path = vendors_dir / "Google.yaml"
        vendor_path.write_text("""
apiVersion: napt/v1
intune:
  publisher: "Google LLC"
""")

        recipe_path = recipes_dir / "chrome.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Chrome
id: napt-chrome
discovery:
  strategy: url_download
  url: "https://example.com/chrome.msi"
""")

        config = load_effective_config(recipe_path)

        assert config["intune"]["publisher"] == "Google LLC"


class TestDynamicInjection:
    """Tests for dynamic value injection."""

    def test_appscriptdate_injection(self, create_yaml_file, sample_recipe_data):
        """Test that AppScriptDate is injected with today's date."""
        from datetime import date

        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)
        config = load_effective_config(recipe_path)

        today = date.today().strftime("%Y-%m-%d")
        app_vars = config.get("psadt", {}).get("app_vars", {})
        if "AppScriptDate" in app_vars:
            assert app_vars["AppScriptDate"] == today

    def test_require_admin_defaults_true_for_system_scope(self):
        """Tests that _inject_dynamic_values defaults RequireAdmin to true for system scope."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {"psadt": {"app_vars": {}}, "intune": {"run_as_account": "system"}}
        _inject_dynamic_values(cfg)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True

    def test_require_admin_defaults_false_for_user_scope(self):
        """Tests that _inject_dynamic_values defaults RequireAdmin to false for user scope."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {"psadt": {"app_vars": {}}, "intune": {"run_as_account": "user"}}
        _inject_dynamic_values(cfg)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is False

    def test_require_admin_explicit_recipe_value_not_overridden(self):
        """Tests that an explicit RequireAdmin from recipe is not overridden."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {
            "psadt": {"app_vars": {"RequireAdmin": True}},
            "intune": {"run_as_account": "user"},
        }
        provenance = {
            "psadt": {"app_vars": {"RequireAdmin": "recipe"}},
            "intune": {"run_as_account": "code_default"},
        }
        _inject_dynamic_values(cfg, provenance)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True

    def test_require_admin_defaults_true_for_default_run_as_account(self):
        """Tests that RequireAdmin defaults to true with default run_as_account."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {
            "psadt": {"app_vars": {}},
            "intune": {"run_as_account": "system"},
        }
        _inject_dynamic_values(cfg)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True


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
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Test App
id: test-app
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        config = load_effective_config(recipe_path)

        # Should have code defaults applied
        assert config["psadt"]["release"] == "latest"
        assert config["directories"]["build"] == "builds"
        assert config["intune"]["build_types"] == "both"
        assert config["logging"]["log_format"] == "cmtrace"

    def test_org_yaml_overrides_code_defaults(self, tmp_test_dir):
        """Tests that org.yaml values override code defaults."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  release: "4.0.0"
logging:
  log_format: "cmtrace"
""")

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("""
apiVersion: napt/v1
name: Test App
id: test-app
discovery:
  strategy: url_download
  url: "https://example.com/app.msi"
""")

        config = load_effective_config(recipe_path)

        # org.yaml values should override code defaults
        assert config["psadt"]["release"] == "4.0.0"
        # But code defaults should still provide unspecified values
        assert config["directories"]["build"] == "builds"

    def test_code_defaults_structure_matches_expected(self):
        """Tests that code defaults have expected structure."""
        assert "psadt" in DEFAULT_CONFIG
        assert "intune" in DEFAULT_CONFIG
        assert "logging" in DEFAULT_CONFIG
        assert "directories" in DEFAULT_CONFIG

        assert "release" in DEFAULT_CONFIG["psadt"]
        assert "app_vars" in DEFAULT_CONFIG["psadt"]
        assert "build" in DEFAULT_CONFIG["directories"]
        assert "build_types" in DEFAULT_CONFIG["intune"]
        assert "log_format" in DEFAULT_CONFIG["logging"]

    def test_org_yaml_template_covers_all_sections(self):
        """Tests that ORG_YAML_TEMPLATE mentions all DEFAULT_CONFIG sections.

        This test catches drift between the code defaults and the template
        shown to users via `napt init`. If a new section is added to
        DEFAULT_CONFIG but not to the template, this test will fail.
        """
        for section in DEFAULT_CONFIG.keys():
            assert section in ORG_YAML_TEMPLATE, (
                f"Section '{section}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template in "
                f"napt/config/defaults.py to include this section."
            )

        nested_checks = [
            ("psadt", "release"),
            ("psadt", "brand_pack"),
            ("psadt", "app_vars"),
            ("directories", "build"),
            ("intune", "build_types"),
            ("intune", "detection"),
            ("logging", "log_format"),
            ("intunewin", "release"),
        ]

        for parent, key in nested_checks:
            assert key in ORG_YAML_TEMPLATE, (
                f"Key '{parent}.{key}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template."
            )


class TestValidationInLoader:
    """Tests that load_effective_config enforces validation."""

    def test_missing_name_raises_config_error(self, tmp_test_dir):
        """Tests that a recipe missing 'name' raises ConfigError."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
        )

        with pytest.raises(ConfigError, match="name"):
            load_effective_config(recipe_path)

    def test_missing_id_raises_config_error(self, tmp_test_dir):
        """Tests that a recipe missing 'id' raises ConfigError."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nname: Test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
        )

        with pytest.raises(ConfigError, match="id"):
            load_effective_config(recipe_path)

    def test_missing_discovery_raises_config_error(self, tmp_test_dir):
        """Tests that a recipe missing 'discovery' raises ConfigError."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text("apiVersion: napt/v1\nname: Test\nid: test\n")

        with pytest.raises(ConfigError, match="discovery"):
            load_effective_config(recipe_path)

    def test_invalid_strategy_raises_config_error(self, tmp_test_dir):
        """Tests that an unknown strategy raises ConfigError."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nname: Test\nid: test\n"
            "discovery:\n  strategy: nonexistent\n"
        )

        with pytest.raises(ConfigError):
            load_effective_config(recipe_path)

    def test_valid_recipe_returns_config_with_required_fields(
        self, create_yaml_file, sample_recipe_data
    ):
        """Tests that a valid recipe returns config with required fields accessible."""
        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)

        config = load_effective_config(recipe_path)

        assert config["name"] == "Test App"
        assert config["id"] == "test-app"
        assert config["discovery"]["strategy"] == "url_download"

    def test_device_restart_behavior_default_is_based_on_return_code(
        self, create_yaml_file, sample_recipe_data
    ):
        """Tests that device_restart_behavior defaults to basedOnReturnCode."""
        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)

        config = load_effective_config(recipe_path)

        assert config["intune"]["device_restart_behavior"] == "basedOnReturnCode"

    def test_warnings_do_not_raise(self, tmp_test_dir):
        """Tests that warnings (unknown fields) do not cause ConfigError."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nname: Test\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
            "intune:\n  typo_field: value\n"
        )

        config = load_effective_config(recipe_path)

        assert config["name"] == "Test"

    def test_validate_config_and_validate_recipe_agree(self, tmp_test_dir):
        """Tests that validate_config and validate_recipe report the same errors."""
        from napt.validation import validate_recipe

        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
        )

        recipe_result = validate_recipe(recipe_path)

        assert recipe_result.status == "invalid"
        assert any("name" in err for err in recipe_result.errors)

    def test_all_required_fields_validated(self):
        """Tests that every required field produces a validation error when missing."""
        from napt.validation import validate_config

        # A complete valid config to selectively remove fields from
        valid_config: dict[str, Any] = {
            "apiVersion": "napt/v1",
            "name": "Test App",
            "id": "test-app",
            "discovery": {
                "strategy": "url_download",
                "url": "https://example.com/app.msi",
            },
        }

        # Top-level required fields
        for field in ["apiVersion", "name", "id", "discovery"]:
            incomplete = dict(valid_config)
            del incomplete[field]
            result = validate_config(incomplete)
            assert (
                result.status == "invalid"
            ), f"Removing '{field}' should produce a validation error"
            assert any(
                field in err for err in result.errors
            ), f"Error message should mention '{field}'"

        # Nested required: discovery.strategy
        no_strategy = dict(valid_config)
        no_strategy["discovery"] = {"url": "https://example.com/app.msi"}
        result = validate_config(no_strategy)
        assert (
            result.status == "invalid"
        ), "Removing 'discovery.strategy' should produce a validation error"
        assert any(
            "strategy" in err for err in result.errors
        ), "Error message should mention 'strategy'"
