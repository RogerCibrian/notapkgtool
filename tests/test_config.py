"""Tests for napt.config.loader module.

Tests configuration loading and merging including:
- YAML file loading
- Layer merging (code defaults -> org -> vendor -> parent -> recipe)
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
        """Tests that RequireAdmin defaults to true for system scope."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {"psadt": {"app_vars": {}}, "intune": {"run_as_account": "system"}}
        _inject_dynamic_values(cfg)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True

    def test_require_admin_defaults_false_for_user_scope(self):
        """Tests that RequireAdmin defaults to false for user scope."""
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
        assert config["logging"]["log_rotation_mb"] == 3

    def test_org_yaml_overrides_code_defaults(self, tmp_test_dir):
        """Tests that org.yaml values override code defaults."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()

        org_path = defaults_dir / "org.yaml"
        org_path.write_text("""
apiVersion: napt/v1
psadt:
  release: "4.0.0"
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
        assert "icons" in DEFAULT_CONFIG["directories"]
        assert "build_types" in DEFAULT_CONFIG["intune"]
        assert "log_rotation_mb" in DEFAULT_CONFIG["logging"]

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
            ("directories", "icons"),
            ("intune", "build_types"),
            ("intune", "detection"),
            ("logging", "log_rotation_mb"),
            ("intunewin", "release"),
        ]

        for parent, key in nested_checks:
            assert key in ORG_YAML_TEMPLATE, (
                f"Key '{parent}.{key}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template."
            )


class TestLogoPathResolution:
    """Tests for intune.logo_path resolution in _resolve_known_paths."""

    @staticmethod
    def _write_recipe(recipes_dir, logo_path_line: str = "") -> Any:
        recipe_path = recipes_dir / "test.yaml"
        intune_section = (
            f"intune:\n  logo_path: {logo_path_line}\n" if (logo_path_line) else ""
        )
        recipe_path.write_text(
            "apiVersion: napt/v1\nname: Test\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n" + intune_section
        )
        return recipe_path

    def test_relative_logo_path_resolves_against_recipe_dir(self, tmp_test_dir):
        """Tests that a relative logo_path resolves against the recipe dir."""
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()
        recipe_path = self._write_recipe(recipes_dir, "assets/logo.png")

        config = load_effective_config(recipe_path)

        expected = str((recipes_dir / "assets" / "logo.png").resolve())
        assert config["intune"]["logo_path"] == expected

    def test_absolute_logo_path_is_unchanged(self, tmp_test_dir):
        """Tests that an absolute logo_path is left untouched."""
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()
        absolute = str((tmp_test_dir / "elsewhere" / "logo.png").resolve())
        recipe_path = self._write_recipe(recipes_dir, f"'{absolute}'")

        config = load_effective_config(recipe_path)

        assert config["intune"]["logo_path"] == absolute

    def test_unset_logo_path_stays_unset(self, tmp_test_dir):
        """Tests that a recipe without logo_path gets no logo_path value."""
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()
        recipe_path = self._write_recipe(recipes_dir)

        config = load_effective_config(recipe_path)

        assert not config["intune"].get("logo_path")

    def test_org_level_logo_path_resolves_against_defaults_root(self, tmp_test_dir):
        """Tests that an org-set logo_path resolves next to org.yaml."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        (defaults_dir / "org.yaml").write_text(
            "apiVersion: napt/v1\nintune:\n  logo_path: assets/org-logo.png\n"
        )
        org_logo = defaults_dir / "assets" / "org-logo.png"
        org_logo.parent.mkdir()
        org_logo.write_bytes(b"png")
        recipes_dir = tmp_test_dir / "recipes"
        recipes_dir.mkdir()
        recipe_path = self._write_recipe(recipes_dir)

        config = load_effective_config(recipe_path)

        assert config["intune"]["logo_path"] == str(org_logo.resolve())

    def test_recipe_relative_logo_path_wins_over_defaults_root(self, tmp_test_dir):
        """Tests that a recipe-relative logo file wins when both exist."""
        defaults_dir = tmp_test_dir / "defaults"
        defaults_dir.mkdir()
        (defaults_dir / "org.yaml").write_text("apiVersion: napt/v1\n")
        for base in (tmp_test_dir, tmp_test_dir / "recipes"):
            logo = base / "assets" / "logo.png"
            logo.parent.mkdir(parents=True)
            logo.write_bytes(b"png")
        recipes_dir = tmp_test_dir / "recipes"
        recipe_path = self._write_recipe(recipes_dir, "assets/logo.png")

        config = load_effective_config(recipe_path)

        expected = str((recipes_dir / "assets" / "logo.png").resolve())
        assert config["intune"]["logo_path"] == expected


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


_PARENT_RECIPE = """apiVersion: napt/v1
name: Base App
id: base-app
discovery:
  strategy: url_download
  url: https://example.com/base.msi
psadt:
  app_vars:
    AppLang: FR
    AppProcessesToClose: [base]
intune:
  run_as_account: user
"""


class TestParentRecipes:
    """Tests for the parent field: merge order, provenance, and errors."""

    @staticmethod
    def _project(
        tmp_test_dir,
        override_body: str = "",
        parent_text: str = _PARENT_RECIPE,
        org_text: str | None = None,
        vendor_text: str | None = None,
    ) -> Any:
        """Writes a base recipe and an override naming it, returning the override."""
        base_dir = tmp_test_dir / "recipes" / "_base"
        base_dir.mkdir(parents=True)
        (base_dir / "base.yaml").write_text(parent_text)
        vendor_dir = tmp_test_dir / "recipes" / "Google"
        vendor_dir.mkdir()
        override = vendor_dir / "app.override.yaml"
        override.write_text(
            "apiVersion: napt/v1\nparent: ../_base/base.yaml\n"
            "name: Child App\nid: child-app\n" + override_body
        )
        if org_text is not None or vendor_text is not None:
            defaults_dir = tmp_test_dir / "defaults"
            defaults_dir.mkdir()
            (defaults_dir / "org.yaml").write_text(org_text or "apiVersion: napt/v1\n")
            if vendor_text is not None:
                (defaults_dir / "vendors").mkdir()
                (defaults_dir / "vendors" / "Google.yaml").write_text(vendor_text)
        return override

    def test_parent_values_apply_when_override_is_silent(self, tmp_test_dir):
        """Tests that the parent supplies everything the override leaves out."""
        override = self._project(tmp_test_dir)

        config = load_effective_config(override)

        assert config["name"] == "Child App"
        assert config["id"] == "child-app"
        assert config["discovery"]["url"] == "https://example.com/base.msi"
        assert config["psadt"]["app_vars"]["AppLang"] == "FR"

    def test_override_beats_parent(self, tmp_test_dir):
        """Tests that a value set in the override wins over the parent."""
        override = self._project(tmp_test_dir, "psadt:\n  app_vars:\n    AppLang: EN\n")

        config = load_effective_config(override)

        assert config["psadt"]["app_vars"]["AppLang"] == "EN"

    def test_parent_beats_org_and_vendor_defaults(self, tmp_test_dir):
        """Tests that the parent layer wins over org and vendor defaults."""
        override = self._project(
            tmp_test_dir,
            org_text="apiVersion: napt/v1\npsadt:\n  app_vars:\n    AppLang: DE\n",
            vendor_text="psadt:\n  app_vars:\n    AppLang: IT\n",
        )

        config = load_effective_config(override)

        assert config["psadt"]["app_vars"]["AppLang"] == "FR"

    def test_override_list_replaces_parent_list(self, tmp_test_dir):
        """Tests that a list in the override replaces the parent's list."""
        override = self._project(
            tmp_test_dir, "psadt:\n  app_vars:\n    AppProcessesToClose: [child]\n"
        )

        config = load_effective_config(override)

        assert config["psadt"]["app_vars"]["AppProcessesToClose"] == ["child"]

    def test_parent_key_is_not_in_returned_config(self, tmp_test_dir):
        """Tests that the parent pointer is dropped from the merged config."""
        override = self._project(tmp_test_dir)

        config = load_effective_config(override)

        assert "parent" not in config
        assert "parent" not in config["_provenance"]

    def test_provenance_labels_parent_layer(self, tmp_test_dir):
        """Tests that values from the parent are attributed to the parent layer."""
        override = self._project(tmp_test_dir)

        config = load_effective_config(override)

        provenance = config["_provenance"]
        assert provenance["psadt"]["app_vars"]["AppLang"] == "parent"
        assert provenance["name"] == "recipe"

    def test_require_admin_from_parent_is_respected(self, tmp_test_dir):
        """Tests that a RequireAdmin set by the parent is not recomputed."""
        parent = _PARENT_RECIPE.replace(
            "    AppLang: FR\n", "    AppLang: FR\n    RequireAdmin: true\n"
        )
        override = self._project(tmp_test_dir, parent_text=parent)

        config = load_effective_config(override)

        assert config["intune"]["run_as_account"] == "user"
        assert config["psadt"]["app_vars"]["RequireAdmin"] is True

    def test_parent_logo_path_resolves_against_override_dir(self, tmp_test_dir):
        """Tests that a parent's relative logo_path resolves next to the override."""
        parent = _PARENT_RECIPE + "  logo_path: logo.png\n"
        override = self._project(tmp_test_dir, parent_text=parent)

        config = load_effective_config(override)

        expected = str((override.parent / "logo.png").resolve())
        assert config["intune"]["logo_path"] == expected

    def test_missing_parent_raises(self, tmp_test_dir):
        """Tests that a parent path that does not exist is a ConfigError."""
        override = self._project(tmp_test_dir)
        (tmp_test_dir / "recipes" / "_base" / "base.yaml").unlink()

        with pytest.raises(ConfigError, match="Parent recipe not found"):
            load_effective_config(override)

    def test_parent_chain_raises(self, tmp_test_dir):
        """Tests that a parent declaring its own parent is a ConfigError."""
        override = self._project(
            tmp_test_dir, parent_text="parent: other.yaml\n" + _PARENT_RECIPE
        )

        with pytest.raises(ConfigError, match="Parent chains are not supported"):
            load_effective_config(override)

    def test_non_string_parent_raises(self, tmp_test_dir):
        """Tests that a non-string parent value is a ConfigError."""
        override = self._project(tmp_test_dir)
        override.write_text("apiVersion: napt/v1\nparent: 5\nname: X\nid: x\n")

        with pytest.raises(ConfigError, match="non-empty string"):
            load_effective_config(override)

    def test_invalid_parent_content_names_parent_in_error(self, tmp_test_dir):
        """Tests that a schema error inherited from the parent names the parent."""
        parent = _PARENT_RECIPE.replace("url_download", "bogus_strategy")
        override = self._project(tmp_test_dir, parent_text=parent)

        with pytest.raises(ConfigError, match=r"parent: .*base\.yaml"):
            load_effective_config(override)

    def test_parent_and_child_both_setting_a_section_merges(self, tmp_test_dir):
        """Tests that a child merges into a parent-set section instead of crashing."""
        override = self._project(
            tmp_test_dir,
            override_body="discovery:\n  url: https://vendor.example.com/child.msi\n",
        )

        config = load_effective_config(override)

        assert config["discovery"]["url"] == "https://vendor.example.com/child.msi"
        assert config["discovery"]["strategy"] == "url_download"
        provenance = config["_provenance"]["discovery"]
        assert provenance["url"] == "recipe"
        assert provenance["strategy"] == "parent"


class TestUnreadableRecipeFiles:
    """Tests that a recipe file that cannot be read is a ConfigError."""

    def test_directory_path_is_a_config_error(self, tmp_test_dir):
        """Tests that pointing at a folder does not raise a raw OSError."""
        with pytest.raises(ConfigError, match="Cannot read"):
            load_effective_config(tmp_test_dir)

    def test_utf16_file_is_a_config_error(self, tmp_test_dir):
        """Tests that a file saved as UTF-16 names the encoding in the error."""
        recipe = tmp_test_dir / "recipe.yaml"
        recipe.write_text("apiVersion: napt/v1\nname: U\nid: u\n", encoding="utf-16")

        with pytest.raises(ConfigError, match="not UTF-8"):
            load_effective_config(recipe)


class TestEmptySections:
    """Tests that a section key with nothing under it is rejected, not crashed on."""

    @pytest.mark.parametrize("section", ["psadt", "intune", "logging", "deployment"])
    def test_empty_top_level_section(self, tmp_test_dir, section):
        """Tests that an empty section is a validation error, not a TypeError."""
        recipe = tmp_test_dir / "recipe.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: E\nid: e\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
            f"{section}:\n"
        )

        with pytest.raises(ConfigError, match=f"{section}: Must be a dictionary"):
            load_effective_config(recipe)

    @pytest.mark.parametrize(
        ("body", "path"),
        [
            ("psadt:\n  app_vars:\n", "psadt.app_vars"),
            ("intune:\n  detection:\n", "intune.detection"),
        ],
    )
    def test_empty_nested_section(self, tmp_test_dir, body, path):
        """Tests that an empty nested section is reported by its full path."""
        recipe = tmp_test_dir / "recipe.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: E\nid: e\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n" + body
        )

        with pytest.raises(ConfigError, match=f"{path}: Must be a dictionary"):
            load_effective_config(recipe)
