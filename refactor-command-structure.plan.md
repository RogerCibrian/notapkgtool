# Refactor Command Structure: Rename `check` → `discover` and Add `validate`

## Overview

Refactor NAPT's command structure to provide clearer separation between recipe validation and version discovery. This establishes a foundation for the future `napt update` hero command.

## Goals

1. **Rename `napt check` → `napt discover`** - More accurately describes version discovery workflow
2. **Add `napt validate`** - Lightweight recipe syntax/schema validation (no downloads)
3. **Update all references** - Tests, docs, examples
4. **No breaking changes to APIs** - Only CLI command names change

## Motivation

### Current State
```bash
napt check recipes/Google/chrome.yaml
# Purpose unclear: Is it checking syntax? Checking for updates? Downloading?
```

### After Refactor
```bash
# Lightweight validation (fast, no network)
napt validate recipes/Google/chrome.yaml

# Full version discovery (API calls + download)
napt discover recipes/Google/chrome.yaml
```

### Benefits
- ✅ Clear command semantics
- ✅ Aligns with internal naming (`DiscoveryStrategy`)
- ✅ Separates validation from discovery
- ✅ Sets up for future `napt update` orchestration
- ✅ Better CI/CD integration (fast validation on PRs, discovery on schedule)

## Implementation Plan

### Phase 1: Add `validate` Command

#### 1.1 Create Validation Module

**File:** `notapkgtool/validation.py` (new, ~150-200 lines)

Create validation logic that checks:
- YAML syntax is valid
- `apiVersion` field present and supported
- `apps` list exists and not empty
- Required fields per app: `name`, `id`, `source`
- Strategy exists in registry
- Strategy-specific configuration fields

**Key function:**
```python
def validate_recipe(recipe_path: Path, verbose: bool = False) -> dict[str, Any]:
    """
    Validate recipe without downloading anything.
    
    Returns dict with:
    - status: "valid" or "invalid"
    - errors: List of validation errors
    - warnings: List of non-critical issues
    - app_count: Number of apps in recipe
    """
```

#### 1.2 Add Strategy Config Validation

**File:** `notapkgtool/discovery/base.py`

Add optional validation method to protocol:
```python
class DiscoveryStrategy(Protocol):
    def validate_config(self, app_config: dict[str, Any]) -> list[str]:
        """
        Validate strategy-specific configuration.
        
        Returns list of error messages (empty if valid).
        Does NOT make network calls or download files.
        """
        ...
```

#### 1.3 Implement Config Validation in Each Strategy

**Files:**
- `notapkgtool/discovery/http_static.py`
- `notapkgtool/discovery/url_regex.py`
- `notapkgtool/discovery/github_release.py`
- `notapkgtool/discovery/http_json.py`

Add `validate_config()` method to each strategy class:
```python
def validate_config(self, app_config: dict[str, Any]) -> list[str]:
    errors = []
    source = app_config.get("source", {})
    
    # Check required fields
    if "url" not in source:
        errors.append("Missing required field: source.url")
    
    # Check field types
    if not isinstance(source.get("url"), str):
        errors.append("source.url must be a string")
    
    return errors
```

#### 1.4 Add CLI Command

**File:** `notapkgtool/cli.py`

Add `cmd_validate()` function and register parser:
```python
def cmd_validate(args: argparse.Namespace) -> int:
    """
    Handler for 'napt validate' command.
    
    Validates recipe syntax and configuration without making
    network calls or downloading files. Fast and safe.
    """
    # Implementation calls validate_recipe()
    pass

# In main():
parser_validate = subparsers.add_parser(
    "validate",
    help="Validate recipe syntax and configuration (no downloads)",
    description="Check recipe YAML for syntax errors and configuration issues.",
)
```

#### 1.5 Add Tests

**File:** `tests/test_validation.py` (new, ~200-250 lines)

Test coverage:
- Valid recipe passes validation
- Missing required fields detected
- Invalid YAML syntax detected
- Unknown strategy detected
- Strategy-specific validation works
- Multiple apps in one recipe
- Helpful error messages
- Verbose output mode

**File:** `tests/test_discovery.py`

Add validation tests for each strategy's `validate_config()`.

### Phase 2: Rename `check` → `discover`

#### 2.1 Rename CLI Command

**File:** `notapkgtool/cli.py`

Changes:
- Rename `cmd_check()` → `cmd_discover()`
- Update docstrings (s/check/discover/g)
- Update parser name from `"check"` → `"discover"`
- Update help text
- Update comments

#### 2.2 Rename Core Function

**File:** `notapkgtool/core.py`

Changes:
- Rename `check_recipe()` → `discover_recipe()`
- Update docstrings
- Update function comments
- Keep the same functionality

#### 2.3 Update Tests

**File:** `tests/test_core.py`

Changes:
- Rename `TestCheckRecipe` → `TestDiscoverRecipe`
- Rename `test_check_recipe_*` → `test_discover_recipe_*`
- Update all calls to `check_recipe()` → `discover_recipe()`
- Update docstrings

**File:** `tests/test_cli.py` (if exists)

Update any CLI tests that reference `check` command.

#### 2.4 Update Documentation

**File:** `README.md`

Changes:
- Update Quick Start section
- Change all `napt check` → `napt discover`
- Add new `napt validate` section
- Update feature list
- Update workflow examples

**File:** `DOCUMENTATION.md`

Changes:
- Update Commands section
- Add `napt validate` documentation
- Rename `napt check` → `napt discover`
- Update all code examples
- Update workflow diagrams/explanations
- Add comparison table:

```markdown
| Command | Network | Download | Purpose |
|---------|---------|----------|---------|
| validate | No | No | Syntax/config check |
| discover | Yes | Yes | Find latest version |
```

#### 2.5 Update Example Scripts

**File:** `tests/scripts/manual_test_http_json.py`

Update any references to `check_recipe` → `discover_recipe`.

### Phase 3: Update Imports and Exports

#### 3.1 Update Module Exports

**File:** `notapkgtool/__init__.py`

Changes:
- Export `validate_recipe` from validation module
- Update `check_recipe` → `discover_recipe` export
- Update docstring

**File:** `notapkgtool/core.py`

Update `__all__` if present.

**File:** `notapkgtool/validation.py`

Add proper exports:
```python
__all__ = ["validate_recipe", "ValidationError"]
```

### Phase 4: Clean Up and Polish

#### 4.1 Update CLI Help Text

Ensure help output is clear and consistent:
```bash
$ napt --help

Commands:
  validate    Validate recipe syntax (fast, no downloads)
  discover    Discover latest version and download installer

$ napt validate --help
$ napt discover --help
```

#### 4.2 Fix Linter Warnings

**File:** `notapkgtool/discovery/url_regex.py`

Fix the SyntaxWarning about invalid escape sequences (use raw strings for regex).

#### 4.3 Update Examples

Add example usage to docstrings showing both commands:
```python
"""
Examples
--------
Validate recipe syntax:
    $ napt validate recipes/Google/chrome.yaml

Discover latest version:
    $ napt discover recipes/Google/chrome.yaml
"""
```

### Phase 5: Testing and Verification

#### 5.1 Run Test Suite

```bash
poetry run pytest -v
# Should show: All tests passing with new names
```

#### 5.2 Manual Testing

```bash
# Test validation (should be instant)
napt validate recipes/Google/chrome.yaml
napt validate recipes/**/*.yaml

# Test discovery (should work as before)
napt discover recipes/Google/chrome.yaml --verbose
napt discover recipes/Google/chrome.yaml --stateless

# Test error cases
napt validate invalid-recipe.yaml
napt discover broken-recipe.yaml
```

#### 5.3 Verify Help Text

```bash
napt --help
napt validate --help
napt discover --help
```

## Files to Create

**New files:**
- `notapkgtool/validation.py` (~150-200 lines)
- `tests/test_validation.py` (~200-250 lines)
- `refactor-command-structure.plan.md` (this file)

## Files to Modify

**Core functionality:**
- `notapkgtool/cli.py` - Rename cmd_check, add cmd_validate
- `notapkgtool/core.py` - Rename check_recipe → discover_recipe
- `notapkgtool/__init__.py` - Update exports
- `notapkgtool/discovery/base.py` - Add validate_config to protocol
- `notapkgtool/discovery/http_static.py` - Implement validate_config
- `notapkgtool/discovery/url_regex.py` - Implement validate_config, fix regex warnings
- `notapkgtool/discovery/github_release.py` - Implement validate_config
- `notapkgtool/discovery/http_json.py` - Implement validate_config

**Tests:**
- `tests/test_core.py` - Rename test class and functions
- `tests/test_discovery.py` - Add validation tests for each strategy
- `tests/scripts/manual_test_http_json.py` - Update function calls

**Documentation:**
- `README.md` - Update all examples and command references
- `DOCUMENTATION.md` - Add validate section, rename check → discover

**Configuration:**
- `.gitignore` - (no changes needed)
- `pyproject.toml` - (no changes needed)

## Success Criteria

- [ ] `napt validate` command works and validates recipes without downloads
- [ ] `napt discover` command works (renamed from check, same functionality)
- [ ] Old `napt check` command removed (clean break)
- [ ] All 113+ tests passing with new names
- [ ] No linter errors or warnings
- [ ] Documentation fully updated
- [ ] Help text clear and accurate
- [ ] Manual testing confirms both commands work

## Estimated Effort

**Implementation time:** 2-3 hours
- Phase 1 (validate): 1-1.5 hours
- Phase 2 (rename): 30-45 minutes
- Phase 3-5 (cleanup/docs): 30-45 minutes

**Lines of code:**
- New: ~350-450 lines (validation.py + tests)
- Modified: ~50-100 lines (renames, updates)
- Documentation: ~100-150 lines

## Migration Notes

### For Users

No breaking changes to Python API (internal functions can be imported either way).

CLI breaking change:
```bash
# Old (will not work after refactor)
napt check recipes/app.yaml

# New (required after refactor)  
napt discover recipes/app.yaml
```

### For Developers

If you have scripts/CI using `napt check`, update to `napt discover`.

## Future Work

This refactor sets up the foundation for:

1. **`napt compare`** - Compare discovered versions with Intune
2. **`napt build`** - Build PSADT packages
3. **`napt upload`** - Upload to Intune
4. **`napt update`** - Hero command that orchestrates all steps

Command hierarchy will be:
```
napt validate           # Fast check
napt discover           # Find versions
napt compare            # vs Intune
napt build              # Package
napt upload             # Deploy
napt update             # All-in-one (calls above)
```

## Branching Strategy

Follow `branching.md`:

```bash
# Create feature branch
git checkout main
git pull origin main
git checkout -b feature/refactor-command-structure

# After implementation
git add .
git commit -m "feat: rename check to discover, add validate command

- Rename napt check → napt discover for clarity
- Add napt validate for syntax-only checking
- Add validation module with schema validation
- Update all tests and documentation
- No breaking changes to Python API

BREAKING CHANGE: napt check command renamed to napt discover"

git push origin feature/refactor-command-structure
# Create PR
```

## Notes

- This is a **breaking change** for CLI users (command rename)
- Python API can maintain backward compatibility with deprecation warning
- Consider adding a deprecation message if someone tries `napt check`
- Keep git history clean with descriptive commit message
- Since this is pre-1.0, breaking changes are acceptable

