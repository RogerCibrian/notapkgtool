"""Tests for napt.config.loader module.

Tests configuration loading and merging including:
- YAML file loading
- Layer merging (code defaults -> org -> vendor -> parent -> recipe)
- Path resolution
- Dynamic value injection
- Error handling
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from napt.config.defaults import DEFAULT_CONFIG, ORG_YAML_TEMPLATE
from napt.config.loader import (
    LoadedParent,
    collect_recipe_paths,
    load_effective_config,
    load_parent,
    merge_config_layers,
    merge_effective_config,
    register_recipe_id,
    resolve_state_dir,
)
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
        """Tests that a missing recipe is a ConfigError naming the role and path."""
        nonexistent = tmp_test_dir / "nonexistent.yaml"

        with pytest.raises(ConfigError, match=r"Recipe not found: .*nonexistent"):
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
        """Tests that AppScriptDate is injected with today's date and labelled
        as computed in the provenance."""
        from datetime import date

        recipe_path = create_yaml_file("recipe.yaml", sample_recipe_data)
        config = load_effective_config(recipe_path)

        today = date.today().strftime("%Y-%m-%d")
        assert config["psadt"]["app_vars"]["AppScriptDate"] == today
        assert config["_provenance"]["psadt"]["app_vars"]["AppScriptDate"] == "computed"

    @staticmethod
    def _inject(run_as_account: str, **app_vars):
        """Runs the injector on a config whose given app_vars came from org.yaml."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {
            "psadt": {"app_vars": dict(app_vars)},
            "intune": {"run_as_account": run_as_account},
        }
        provenance = {
            "psadt": {"app_vars": {key: "org_yaml" for key in app_vars}},
            "intune": {"run_as_account": "recipe"},
        }
        _inject_dynamic_values(cfg, provenance)
        return cfg, provenance

    def test_require_admin_is_computed_true_for_system_scope(self):
        """Tests that RequireAdmin is true for a system install and says so."""
        cfg, provenance = self._inject("system")

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True
        assert provenance["psadt"]["app_vars"]["RequireAdmin"] == "computed"

    def test_require_admin_is_computed_false_for_user_scope(self):
        """Tests that RequireAdmin is false for a per-user install."""
        cfg, _ = self._inject("user")

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is False

    def test_appscriptdate_set_in_a_layer_is_kept(self):
        """Tests that a pinned AppScriptDate is neither replaced nor relabeled."""
        cfg, provenance = self._inject("system", AppScriptDate="2026-01-01")

        assert cfg["psadt"]["app_vars"]["AppScriptDate"] == "2026-01-01"
        assert provenance["psadt"]["app_vars"]["AppScriptDate"] == "org_yaml"

    def test_require_admin_set_in_a_layer_is_kept(self):
        """Tests that a RequireAdmin written in org.yaml wins over the computed
        value, which is why the repo's org.yaml must not set it."""
        cfg, provenance = self._inject("user", RequireAdmin=True)

        assert cfg["psadt"]["app_vars"]["RequireAdmin"] is True
        assert provenance["psadt"]["app_vars"]["RequireAdmin"] == "org_yaml"

    def test_wrong_shape_sections_are_left_for_validation(self):
        """Tests that an app_vars that is not a mapping injects nothing and
        raises nothing; validation reports the shape."""
        from napt.config.loader import _inject_dynamic_values

        cfg = {"psadt": {"app_vars": ["x"]}, "intune": {"run_as_account": "system"}}

        _inject_dynamic_values(cfg, {"psadt": {}, "intune": {}})

        assert cfg["psadt"]["app_vars"] == ["x"]


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

        with pytest.raises(ConfigError, match="must be a mapping"):
            load_effective_config(recipe_path)

    @staticmethod
    def _project(tmp_test_dir, org_yaml: str, vendor_yaml: str | None = None):
        """Writes a project with one recipe under recipes/Vendor/."""
        (tmp_test_dir / "defaults" / "vendors").mkdir(parents=True)
        (tmp_test_dir / "defaults" / "org.yaml").write_text(org_yaml, encoding="utf-8")
        if vendor_yaml is not None:
            (tmp_test_dir / "defaults" / "vendors" / "Vendor.yaml").write_text(
                vendor_yaml, encoding="utf-8"
            )
        recipe = tmp_test_dir / "recipes" / "Vendor" / "app.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_text(
            "apiVersion: napt/v1\nname: App\nid: app\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n",
            encoding="utf-8",
        )
        return recipe

    def test_non_mapping_org_yaml_is_an_error(self, tmp_test_dir):
        """Tests that an org.yaml whose top level is a list is refused like a
        recipe would be, instead of being skipped without a word."""
        recipe = self._project(tmp_test_dir, "- psadt\n- intune\n")

        with pytest.raises(ConfigError, match=r"must be a mapping.*org\.yaml"):
            load_effective_config(recipe)

    def test_non_mapping_vendor_file_is_an_error(self, tmp_test_dir):
        """Tests that a vendor file whose top level is a scalar is refused."""
        recipe = self._project(tmp_test_dir, "apiVersion: napt/v1\n", "just text\n")

        with pytest.raises(ConfigError, match=r"must be a mapping.*Vendor\.yaml"):
            load_effective_config(recipe)

    def test_debug_dump_is_not_built_when_debug_is_off(self, tmp_test_dir):
        """Tests that a load does not serialize every layer to YAML text that
        the logger then discards."""
        recipe = self._project(tmp_test_dir, "apiVersion: napt/v1\n")

        with patch("napt.config.loader.yaml.dump") as dump:
            load_effective_config(recipe)

        dump.assert_not_called()

    def test_debug_dump_shows_the_final_configuration(self, tmp_test_dir, capsys):
        """Tests that the final dump is taken after injection, so it shows the
        configuration the command actually uses."""
        from napt.logging import get_logger, set_global_logger

        recipe = self._project(tmp_test_dir, "apiVersion: napt/v1\n")
        set_global_logger(get_logger(debug=True))

        load_effective_config(recipe)

        out = capsys.readouterr().out
        final = out.index("--- Final Merged Configuration ---")
        assert "AppScriptDate" in out[final:]
        assert "RequireAdmin: true" in out[final:]


def _default_config_leaves() -> list[tuple[str, str]]:
    """Lists every (section, key) a value sits under in DEFAULT_CONFIG.

    Keys nested deeper than the section (``psadt.app_vars.AppLang``) are
    reported with their top-level section, since the template is checked
    per section.
    """

    def walk(node: Any) -> list[str]:
        keys: list[str] = []
        for key, value in node.items():
            keys.append(key)
            if isinstance(value, dict) and value:
                keys.extend(walk(value))
        return keys

    return [
        (section, key)
        for section, value in DEFAULT_CONFIG.items()
        if isinstance(value, dict)
        for key in walk(value)
    ]


def _template_sections() -> dict[str, str]:
    """Splits ORG_YAML_TEMPLATE into its top-level sections.

    A section starts at a line that is a top-level key, commented out or
    not (``# psadt:`` or ``apiVersion:``), and runs to the next such line.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    for line in ORG_YAML_TEMPLATE.splitlines():
        stripped = line[2:] if line.startswith("# ") else line
        if stripped and not stripped.startswith((" ", "#")) and stripped.endswith(":"):
            current = stripped[:-1]
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


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
        """Tests that ORG_YAML_TEMPLATE names every key in DEFAULT_CONFIG.

        The template is what `napt init` shows users as the menu of
        settings, so a default added to DEFAULT_CONFIG without a line in
        the template fails here, whether it is a new section or a new key
        inside an existing one.
        """
        sections = _template_sections()
        for section in DEFAULT_CONFIG.keys():
            assert section in sections, (
                f"Section '{section}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in ORG_YAML_TEMPLATE. Update the template in "
                f"napt/config/defaults.py to include this section."
            )

        for parent, key in _default_config_leaves():
            assert f"{key}:" in sections[parent], (
                f"Key '{parent}.{key}' exists in DEFAULT_CONFIG but is not "
                f"mentioned in the '{parent}' section of ORG_YAML_TEMPLATE. "
                "Update the template."
            )

    def test_org_yaml_template_drops_the_old_cache_key(self):
        """Tests that the template shows directories.cache, not psadt.cache_dir."""
        sections = _template_sections()
        assert "cache_dir" not in ORG_YAML_TEMPLATE
        assert "cache:" in sections["directories"]
        assert "cache_dir" not in DEFAULT_CONFIG["psadt"]
        assert DEFAULT_CONFIG["directories"]["cache"] == "cache"

    def test_org_yaml_template_names_every_layer(self):
        """Tests that the hierarchy comment lists the parent recipe layer."""
        assert "Parent recipe" in ORG_YAML_TEMPLATE


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
    """Tests that load_effective_config enforces validation.

    The validation rules themselves are tested in test_validation.py; these
    cover the loader path: an error raises, a warning does not.
    """

    def test_validation_error_raises_config_error(self, tmp_test_dir):
        """Tests that a recipe failing validation cannot be loaded."""
        recipe_path = tmp_test_dir / "recipe.yaml"
        recipe_path.write_text(
            "apiVersion: napt/v1\nid: test\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n"
        )

        with pytest.raises(ConfigError, match="name"):
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

    def test_utf16_parent_names_the_encoding(self, tmp_test_dir):
        """Tests that a parent saved as UTF-16 is reported like a recipe."""
        override = self._project(tmp_test_dir)
        base = tmp_test_dir / "recipes" / "_base" / "base.yaml"
        base.write_text(_PARENT_RECIPE, encoding="utf-16")

        with pytest.raises(ConfigError, match="not UTF-8"):
            load_effective_config(override)


_VENDORED_PATH = "github.com/someorg/napt-recipes/recipes/Google/chrome.yaml"

_FOREIGN_PARENT = """apiVersion: napt/v1
name: Google Chrome
id: chrome
discovery:
  strategy: url_download
  url: https://example.com/chrome.msi
psadt:
  release: "4.0.0"
  app_vars:
    AppLang: FR
intune:
  build_types: update_only
  description: From upstream
deployment:
  rings:
    - name: theirs
      groups: ["their-group"]
"""


class TestForeignParents:
    """Tests for a parent under upstream/: the hash check and the allow list."""

    @staticmethod
    def _project(
        tmp_test_dir,
        parent_text: str = _FOREIGN_PARENT,
        *,
        tracked: bool = True,
        recorded_text: str | None = None,
        org_text: str = "apiVersion: napt/v1\n",
    ) -> Any:
        """Writes a vendored parent, its lockfile entry, and an override."""
        from napt.upstream.lock import canonical_sha256

        vendored = tmp_test_dir / "upstream" / Path(_VENDORED_PATH)
        vendored.parent.mkdir(parents=True)
        vendored.write_text(parent_text)
        if tracked:
            recorded = (recorded_text or parent_text).encode()
            (tmp_test_dir / "upstream.yaml").write_text(
                "apiVersion: napt/v1\n"
                "repos:\n"
                "  - url: https://github.com/someorg/napt-recipes.git\n"
                "    ref: main\n"
                "    commit: 4f2a9c1e\n"
                "    recipes:\n"
                "      - path: recipes/Google/chrome.yaml\n"
                "        override: recipes/Google/chrome.override.yaml\n"
                "        blob: 9c1d2e3f\n"
                f"        sha256: {canonical_sha256(recorded)}\n"
            )
        defaults = tmp_test_dir / "defaults"
        defaults.mkdir()
        (defaults / "org.yaml").write_text(org_text)
        override = tmp_test_dir / "recipes" / "Google" / "chrome.override.yaml"
        override.parent.mkdir(parents=True)
        override.write_text(
            "apiVersion: napt/v1\n"
            f"parent: ../../upstream/{_VENDORED_PATH}\n"
            "name: Google Chrome\nid: napt-chrome\n"
        )
        return override

    def test_tenant_keys_from_a_foreign_parent_are_dropped(self, tmp_test_dir):
        """Tests that org.yaml wins on keys the parent is not allowed to set."""
        override = self._project(
            tmp_test_dir,
            org_text=(
                "apiVersion: napt/v1\n"
                "deployment:\n  rings:\n    - name: ours\n      groups: [our-group]\n"
                "intune:\n  build_types: both\n"
            ),
        )

        config = load_effective_config(override)

        assert config["deployment"]["rings"][0]["name"] == "ours"
        assert config["intune"]["build_types"] == "both"
        assert config["psadt"]["release"] == "latest"
        assert config["psadt"]["app_vars"]["AppLang"] == "FR"
        assert config["intune"]["description"] == "From upstream"
        assert config["_provenance"]["deployment"]["rings"] == "org_yaml"

    def test_dropped_keys_are_logged_once_without_verbose(self, tmp_test_dir, capsys):
        """Tests that one always-visible line names every dropped key."""
        override = self._project(tmp_test_dir)

        load_effective_config(override)

        lines = [
            line for line in capsys.readouterr().out.splitlines() if "Ignoring" in line
        ]
        assert lines == [
            "[CONFIG] Ignoring from parent (not allowed from upstream recipes): "
            "psadt.release, intune.build_types, deployment"
        ]

    def test_nothing_dropped_prints_nothing(self, tmp_test_dir, capsys):
        """Tests that a parent setting only allowed keys is silent."""
        parent = _FOREIGN_PARENT.replace('  release: "4.0.0"\n', "").replace(
            "  build_types: update_only\n", ""
        )
        parent = parent[: parent.index("deployment:")]
        override = self._project(tmp_test_dir, parent)

        load_effective_config(override)

        assert "Ignoring" not in capsys.readouterr().out

    def test_non_mapping_section_cannot_erase_org_policy(self, tmp_test_dir):
        """Tests that intune: [] in a foreign parent leaves org.yaml's intune intact."""
        parent = _FOREIGN_PARENT.replace(
            "intune:\n  build_types: update_only\n  description: From upstream\n",
            "intune: []\n",
        )
        override = self._project(
            tmp_test_dir,
            parent,
            org_text="apiVersion: napt/v1\nintune:\n  enforce_signature_check: true\n",
        )
        override.write_text(override.read_text() + "intune:\n  description: Ours\n")

        config = load_effective_config(override)

        assert config["intune"]["enforce_signature_check"] is True
        assert config["intune"]["build_types"] == "both"
        assert config["intune"]["description"] == "Ours"

    def test_local_parent_is_not_filtered(self, tmp_test_dir):
        """Tests that a base in recipe-bases/ keeps its tenant keys."""
        base = tmp_test_dir / "recipe-bases" / "base.yaml"
        base.parent.mkdir()
        base.write_text(_FOREIGN_PARENT)
        override = tmp_test_dir / "recipes" / "Google" / "chrome.override.yaml"
        override.parent.mkdir(parents=True)
        override.write_text(
            "apiVersion: napt/v1\nparent: ../../recipe-bases/base.yaml\n"
            "name: Google Chrome\nid: napt-chrome\n"
        )

        config = load_effective_config(override)

        assert config["deployment"]["rings"][0]["name"] == "theirs"
        assert config["psadt"]["release"] == "4.0.0"

    def test_edited_vendored_file_is_refused(self, tmp_test_dir):
        """Tests that a vendored file that drifted from its record fails to load."""
        override = self._project(
            tmp_test_dir, recorded_text=_FOREIGN_PARENT + "# edited later\n"
        )

        with pytest.raises(ConfigError, match="differs from what .* recorded"):
            load_effective_config(override)

    def test_untracked_vendored_file_is_refused(self, tmp_test_dir):
        """Tests that a hand-copied file under upstream/ fails to load."""
        override = self._project(tmp_test_dir, tracked=False)

        with pytest.raises(ConfigError, match="no .*upstream.yaml tracking it"):
            load_effective_config(override)

    def test_check_keys_on_the_parent_location_not_the_override(self, tmp_test_dir):
        """Tests that an override placed elsewhere still gets the check."""
        self._project(tmp_test_dir, tracked=False)
        elsewhere = tmp_test_dir / "apps" / "chrome.yaml"
        elsewhere.parent.mkdir()
        elsewhere.write_text(
            "apiVersion: napt/v1\n"
            f"parent: ../upstream/{_VENDORED_PATH}\n"
            "name: Google Chrome\nid: napt-chrome\n"
        )

        with pytest.raises(ConfigError, match="no .*upstream.yaml tracking it"):
            load_effective_config(elsewhere)

    def test_two_overrides_sharing_a_parent_are_both_checked(self, tmp_test_dir):
        """Tests that the check runs for every override, not the first only."""
        override = self._project(
            tmp_test_dir, recorded_text=_FOREIGN_PARENT + "# edited later\n"
        )
        second = override.with_name("chrome-beta.override.yaml")
        second.write_text(override.read_text().replace("napt-chrome", "beta"))

        for path in (override, second):
            with pytest.raises(ConfigError, match="differs from what"):
                load_effective_config(path)

    def test_linked_parent_into_upstream_is_still_checked(self, tmp_test_dir):
        """Tests that a link from recipe-bases/ cannot make a vendored file local."""
        from tests.upstream.test_vendored import link_directory

        self._project(tmp_test_dir, recorded_text=_FOREIGN_PARENT + "# edited\n")
        vendored_dir = (tmp_test_dir / "upstream" / Path(_VENDORED_PATH)).parent
        link_directory(tmp_test_dir / "recipe-bases", vendored_dir)
        override = tmp_test_dir / "recipes" / "Google" / "linked.override.yaml"
        override.write_text(
            "apiVersion: napt/v1\nparent: ../../recipe-bases/chrome.yaml\n"
            "name: Linked\nid: linked\n"
        )

        with pytest.raises(ConfigError, match="differs from what"):
            load_effective_config(override)

    def test_vendored_copy_run_directly_is_refused(self, tmp_test_dir):
        """Tests that a command on the vendored file points at the override."""
        self._project(tmp_test_dir)
        vendored = tmp_test_dir / "upstream" / Path(_VENDORED_PATH)

        with pytest.raises(ConfigError, match="Run the override"):
            load_effective_config(vendored)

    def test_validate_reports_the_trust_failure(self, tmp_test_dir):
        """Tests that napt validate turns the hash check into an invalid result."""
        from napt.validation import validate_recipe

        override = self._project(
            tmp_test_dir, recorded_text=_FOREIGN_PARENT + "# edited later\n"
        )

        result = validate_recipe(override)

        assert not result.is_valid
        assert "differs from what" in result.errors[0]

    def test_secrets_in_a_foreign_parent_never_reach_validation(self, tmp_test_dir):
        """Tests that a secrets block is dropped before the merge, not an error."""
        parent = _FOREIGN_PARENT + "secrets:\n  TOKEN:\n    hosts: [evil.example]\n"
        override = self._project(tmp_test_dir, parent)

        config = load_effective_config(override)

        assert config["secrets"] == {}

    def test_state_dir_lookup_is_quiet(self, tmp_test_dir, capsys):
        """Tests that resolve_state_dir prints no recipe diagnostics."""
        override = self._project(tmp_test_dir)

        state_dir = resolve_state_dir(override)

        assert state_dir == Path("state")
        assert capsys.readouterr().out == ""


class TestMergeConfigLayers:
    """Tests that merging parsed layers matches merging the same files from disk."""

    @staticmethod
    def _same_config(from_disk: dict, in_memory: dict) -> None:
        """Compares two merged configs, ignoring the date injected at load time."""
        for config in (from_disk, in_memory):
            config["psadt"]["app_vars"].pop("AppScriptDate")
        assert in_memory == from_disk

    def test_matches_disk_merge_with_parent_org_and_vendor(self, tmp_test_dir):
        """Tests that parsed recipe and parent objects merge as the files do."""
        override = TestParentRecipes._project(
            tmp_test_dir,
            override_body="intune:\n  description: Child\n",
            org_text="apiVersion: napt/v1\npsadt:\n  app_vars:\n    AppLang: DE\n",
            vendor_text="psadt:\n  app_vars:\n    AppRevision: '02'\n",
        )
        from_disk, parent_path = merge_effective_config(override)
        recipe_obj = yaml.safe_load(override.read_text())
        parent = load_parent(override, recipe_obj)

        in_memory = merge_config_layers(override, recipe_obj, parent)

        assert parent is not None and parent.path == parent_path
        self._same_config(from_disk, in_memory)
        assert in_memory["_provenance"]["psadt"]["app_vars"]["AppLang"] == "parent"
        assert in_memory["psadt"]["app_vars"]["AppRevision"] == "02"

    def test_matches_disk_merge_without_parent(self, tmp_test_dir):
        """Tests that a plain recipe merges the same from an object."""
        recipe = tmp_test_dir / "recipes" / "Google" / "app.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_text(_PARENT_RECIPE)
        from_disk, parent_path = merge_effective_config(recipe)

        in_memory = merge_config_layers(recipe, yaml.safe_load(recipe.read_text()))

        assert parent_path is None
        self._same_config(from_disk, in_memory)

    def test_does_not_read_the_recipe_from_disk(self, tmp_test_dir):
        """Tests that the recipe object is used even when no file exists yet."""
        recipe = tmp_test_dir / "recipes" / "Google" / "app.override.yaml"
        recipe.parent.mkdir(parents=True)
        base = tmp_test_dir / "recipe-bases" / "base.yaml"
        base.parent.mkdir()
        base.write_text(_PARENT_RECIPE)
        recipe_obj = {
            "apiVersion": "napt/v1",
            "parent": "../../recipe-bases/base.yaml",
            "name": "Unwritten",
            "id": "unwritten",
        }

        merged = merge_config_layers(
            recipe, recipe_obj, LoadedParent(base, yaml.safe_load(base.read_text()))
        )

        assert not recipe.exists()
        assert merged["name"] == "Unwritten"
        assert merged["discovery"]["url"] == "https://example.com/base.msi"
        assert merged["_provenance"]["discovery"] == "parent"


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


class TestSecretsLayer:
    """Tests that only org.yaml can declare secrets."""

    @staticmethod
    def _write(tmp_test_dir, org_body: str, recipe_body: str):
        defaults = tmp_test_dir / "defaults"
        defaults.mkdir()
        (defaults / "org.yaml").write_text("apiVersion: napt/v1\n" + org_body)
        recipes = tmp_test_dir / "recipes"
        recipes.mkdir()
        recipe = recipes / "app.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: App\nid: app\n"
            "discovery:\n  strategy: url_download\n  url: https://x/a.msi\n"
            + recipe_body
        )
        return recipe

    def test_org_secrets_are_loaded(self, tmp_test_dir):
        """Tests that org.yaml secrets reach the effective configuration."""
        recipe = self._write(
            tmp_test_dir, "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n", ""
        )

        config = load_effective_config(recipe)

        assert config["secrets"] == {"API_TOKEN": {"hosts": ["api.vendor.com"]}}

    def test_no_secrets_section_means_none_declared(self, tmp_test_dir):
        """Tests that the section defaults to empty."""
        recipe = self._write(tmp_test_dir, "", "")

        assert load_effective_config(recipe)["secrets"] == {}

    def test_recipe_cannot_add_a_secret(self, tmp_test_dir):
        """Tests that a recipe-declared secret fails the load."""
        recipe = self._write(
            tmp_test_dir, "", "secrets:\n  API_TOKEN:\n    hosts: [evil.example.com]\n"
        )

        with pytest.raises(ConfigError, match="secrets.API_TOKEN"):
            load_effective_config(recipe)

    def test_recipe_cannot_add_a_host_to_an_org_secret(self, tmp_test_dir):
        """Tests that a recipe cannot widen where an org secret may go."""
        recipe = self._write(
            tmp_test_dir,
            "secrets:\n  API_TOKEN:\n    hosts: [api.vendor.com]\n",
            "secrets:\n  API_TOKEN:\n    hosts: [evil.example.com]\n",
        )

        with pytest.raises(ConfigError, match="secrets.API_TOKEN"):
            load_effective_config(recipe)


class TestCollectRecipePaths:
    """Tests for the shared recipe path collector."""

    def test_file_is_returned_as_is(self, tmp_test_dir):
        """Tests that a file path yields itself."""
        recipe = tmp_test_dir / "a.yaml"
        recipe.touch()

        assert collect_recipe_paths(recipe) == [recipe]

    def test_directory_is_scanned_recursively_and_sorted(self, tmp_test_dir):
        """Tests that .yaml and .yml files under the directory are found."""
        (tmp_test_dir / "b").mkdir()
        (tmp_test_dir / "b" / "two.yml").touch()
        (tmp_test_dir / "a.yaml").touch()
        (tmp_test_dir / "notes.txt").touch()

        found = collect_recipe_paths(tmp_test_dir)

        assert found == [tmp_test_dir / "a.yaml", tmp_test_dir / "b" / "two.yml"]

    def test_missing_path_raises(self, tmp_test_dir):
        """Tests that a path that does not exist is a ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            collect_recipe_paths(tmp_test_dir / "nope")

    def test_empty_directory_raises(self, tmp_test_dir):
        """Tests that a directory without recipes is a ConfigError."""
        with pytest.raises(ConfigError, match="No recipe files"):
            collect_recipe_paths(tmp_test_dir)


class TestRegisterRecipeId:
    """Tests for the one id-collision check validate and promote share."""

    def test_first_declaration_is_recorded(self, tmp_test_dir):
        """Tests that a new id is recorded and nothing is reported."""
        sources: dict[str, Path] = {}

        assert register_recipe_id(sources, "app", tmp_test_dir / "a.yaml") is None
        assert sources == {"app": tmp_test_dir / "a.yaml"}

    def test_second_declaration_names_both_files(self, tmp_test_dir):
        """Tests that a repeated id returns the message naming both files."""
        sources: dict[str, Path] = {}
        register_recipe_id(sources, "app", tmp_test_dir / "a.yaml")

        message = register_recipe_id(sources, "app", tmp_test_dir / "b.yaml")

        assert message is not None
        assert "a.yaml" in message and "b.yaml" in message
        assert sources["app"] == tmp_test_dir / "a.yaml"


class TestResolveStateDir:
    """Tests for the state directory a command reads from configuration."""

    @staticmethod
    def _recipe(tmp_test_dir, extra: str = "") -> Path:
        recipes = tmp_test_dir / "recipes"
        recipes.mkdir()
        recipe = recipes / "app.yaml"
        recipe.write_text(
            "apiVersion: napt/v1\nname: App\nid: app\n"
            "discovery:\n  strategy: url_download\n"
            "  url: https://example.com/app.msi\n" + extra,
            encoding="utf-8",
        )
        return recipe

    def test_resolves_configured_state_dir(self, tmp_test_dir):
        """Tests that directories.state is read from the first recipe."""
        recipe = self._recipe(tmp_test_dir, "directories:\n  state: customstate\n")

        assert resolve_state_dir(recipe) == Path("customstate")
        assert resolve_state_dir(recipe.parent) == Path("customstate")

    def test_default_state_dir(self, tmp_test_dir):
        """Tests that the built-in default resolves to state."""
        recipe = self._recipe(tmp_test_dir)

        assert resolve_state_dir(recipe) == Path("state")
