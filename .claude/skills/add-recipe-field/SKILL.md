---
name: add-recipe-field
description: Add a new field to the NAPT recipe YAML schema. Categorizes the field (org-policy / strategy-specific / required / optional / computed) first, then walks the per-category checklist, documentation, changelog, and tests.
user-invocable: true
allowed-tools: Read Edit Write Glob Grep Bash(*python* -m *)
argument-hint: "field name (and optionally a brief description)"
---

You are adding a new field to the NAPT recipe schema. Categorize first: the category determines where validation, defaults, and access logic live. Follow every step in order.

## Step 1: Categorize the new field

Every config value belongs to exactly one category. Use this flowchart:

```
Is this field set the same way across all/most recipes?
  YES → Would an org admin configure it in org.yaml?
    YES → Org-policy
    NO  → Is it required for the feature to work?
      YES → Recipe-required
      NO  → Absent-means-skip
  NO  → Is it specific to a discovery/build strategy?
    YES → Strategy-specific
    NO  → Does it depend on other config values?
      YES → Computed/derived
      NO  → Absent-means-skip
```

Tell the user which category you've assigned and why before writing any code.

## Step 2: Implement per the category checklist

**Org-policy** (e.g., `run_as_account`, `log_rotation_mb`, `build_types`):
- [ ] Add to `DEFAULT_CONFIG` in `napt/config/defaults.py`
- [ ] Add to `ORG_YAML_TEMPLATE` in `napt/config/defaults.py`
- [ ] Add validation in `napt/validation.py`
- [ ] Access with `config["section"]["key"]` (no fallback)
- [ ] Document in `docs/recipe-reference.md`

A test (`test_org_yaml_template_covers_all_sections`) walks every key in `DEFAULT_CONFIG`, nested ones included, and fails when the key's section of `ORG_YAML_TEMPLATE` does not name it. The template is the menu `napt init` hands users, so every default is shown there with its value, commented out.

**Strategy-specific** (e.g., `timeout`, `prerelease`, `method`):
- [ ] Add module constant `_DEFAULT_X` at top of the strategy module
- [ ] Access with `source.get("key", _DEFAULT_X)`
- [ ] Add to strategy's `validate_config()` if required for that strategy
- [ ] Document in `docs/recipe-reference.md`

**Recipe-required** (e.g., `name`, `id`, `discovery.strategy`):
- [ ] Add validation in `napt/validation.py` (error if missing)
- [ ] Access with `config["key"]` (no fallback; a KeyError is a validation bug)
- [ ] Document as required in `docs/recipe-reference.md`

**Absent-means-skip** (e.g., `description`, `logo_path`, `notes`):
- [ ] Access with `config.get("key")` or `if "key" in config:`
- [ ] Add validation in `napt/validation.py` (type/value checks, not presence)
- [ ] Document as optional in `docs/recipe-reference.md`

**Computed/derived** (e.g., `RequireAdmin`, `AppScriptDate`):
- [ ] Add logic to `_inject_dynamic_values` in `napt/config/loader.py`
- [ ] Use provenance to detect explicit overrides vs defaults
- [ ] Document the computed behavior in `docs/recipe-reference.md`

**Validation patterns.** Every section has a schema table in `napt/validation.py` (`_TOP_LEVEL_FIELDS`, `_PSADT_FIELDS`, `_INTUNE_FIELDS`, `_INTUNE_DETECTION_FIELDS`, `_LOGGING_FIELDS`, `_DIRECTORIES_FIELDS`, `_INTUNEWIN_FIELDS`, `_DEPLOYMENT_FIELDS`, and so on). Add the field to its section's table; a key missing from the table is reported as unknown:

```python
_INTUNE_FIELDS: _Schema = {
    "new_field": _Field(str, ["value1", "value2"]),   # type, allowed values
    "new_count": _Field(int, minimum=1, maximum=10),  # type, bounds
}
```

Presence of a required field, and any rule the table cannot express, goes in the section's `_validate_*` function. Strategy-specific fields go in the strategy's `validate_config()` and in the strategy's `FIELDS` set, which drives the unknown-key check for `discovery`.

**Foreign parents.** Decide whether a recipe vendored from another repository may set the field, and record it in `ALLOWED_PARENT_KEYS` in `napt/upstream/vendored.py`: org-policy fields stay off the list; strategy-specific, recipe-required, and absent-means-skip fields go on it. `discovery` is allowed whole. A `psadt` or `intune` field left unclassified fails `test_every_schema_key_is_classified` in `tests/upstream/test_vendored.py`, which also lists the dropped keys; update that list for an org-policy field.

## Step 3: Document in `docs/recipe-reference.md`

Add field documentation following the standard format:

```markdown
#### field_name

**Type:** `string`
**Required:** No
**Default:** `"default_value"`
**Allowed values:** `"value1"`, `"value2"`

Description of what the field does and when to use it.
```

**Field documentation order:** Type → Required → Default (if applicable) → Allowed values (if applicable) → Description → Examples (if helpful)

## Step 4: Update examples

Add the field to example recipes in `docs/common-tasks.md` if it's commonly used, or note it as optional in relevant strategy examples.

## Step 5: Update the changelog

Recipe schema changes are user-facing. Add an entry under `[Unreleased]` in `docs/changelog.md` following Keep a Changelog format (usually `### Added` for a new field). Describe what recipe authors can now do, not the implementation.

## Step 6: Verify implementation

Check these to ensure the field is actually used:
- Search codebase: grep for the field name in `napt/`
- Verify it's read from config in relevant modules
- Check if field exists in defaults but isn't used (planned feature; flag this)

## Step 7: Add tests and run the suite

- Add or extend validation tests for the new field: a valid value, an invalid value, and the missing-field behavior appropriate to its category (error for recipe-required, skip for absent-means-skip, default for the rest).
- Org-policy fields: confirm `test_org_yaml_template_covers_all_sections` still passes.
- Run unit tests:
  ```
  .venv/Scripts/python.exe -m pytest tests/ -m "not integration" -q
  ```
  If anything fails, fix it before finishing.

## Final invariants

All documented fields should either:
- Be validated in `validation.py` AND used in the code, OR
- Be clearly marked as planned/future functionality, OR
- Be removed if no longer needed

Never leave a field that's documented but unimplemented without a "planned" note.
