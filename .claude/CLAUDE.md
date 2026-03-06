# NAPT Project Rules

## Project Principles

**NAPT does:** Discovery, packaging, deployment, state management.

**NAPT does not:** Git operations, PR creation, CI/CD workflow logic. Don't add `--create-pr` flags or git commands.

**No backward compatibility (pre-release):** Implement cleanest solutions directly. Remove deprecated code immediately. No migration paths or fallback logic. After v1.0.0, standard semver applies.

---

## Development Environment

- **Python:** 3.13.5
- **Virtual environment:** `.venv/`
- **Shell:** PowerShell 5.1

**Run Python tools directly:**
```powershell
.venv\Scripts\python.exe -m ruff check --fix napt/ tests/
.venv\Scripts\python.exe -m black napt/ tests/
.venv\Scripts\python.exe -m pytest tests/
```

**Never use `&&`** in PowerShell 5.1. Use `;` or separate commands.

---

## Code Quality

Use **ruff** + **black**. Fix all errors before committing. Never ignore errors. Configuration is in `pyproject.toml`.

```powershell
.venv\Scripts\python.exe -m ruff check --fix napt/ tests/
.venv\Scripts\python.exe -m black napt/ tests/
.venv\Scripts\python.exe -m ruff check napt/ tests/
```

**Line length:** 88 chars max. Break with parentheses or multiple lines.

---

## Docstrings

Use [Google Python Style Guide 3.8](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings) with:

- **Descriptive style:** "Fetches rows" not "Fetch rows"
- **Omit types:** MkDocs extracts from signatures
- **4-space indentation** after section headers
- **Section order:** Summary → Description → Args → Returns → Raises → Example → Note
- **Note is singular:** `Note:` never `Notes:`

**Example section** requires subtitle before code fence:
```python
Example:
    Basic usage:
        ```python
        result = my_function("test")
        ```
```

**Bullet lists in sections:** Indent 4 spaces. In main description: no extra indent, blank line before list.

**Collapsible box (intentional only):** No blank line + 4-space indented bullets:
```python
"""Provides discovery functionality.

Key Features:
    - First item
    - Second item
"""
```

**Complex Returns:** Indent continuation lines to avoid mkdocstrings parsing as definition list:
```python
Returns:
    A dict (key1, key2, key3), where
        key1 is the first thing,
        key2 is the second thing.
```

**Dataclass Returns:** Describe contents only (type already shown by mkdocstrings):
```python
Returns:
    Discovery results and metadata including version, file path, and SHA-256 hash.
```
Don't repeat the class name (DiscoverResult) - mkdocstrings extracts it from the return annotation and auto-links to the dataclass definition where all fields are documented.

**Module docstrings:** Required for all modules. First line is summary, then blank line, then details.

**Test docstrings:** Use `"""Tests that <condition>."""` format. Keep brief.

**Validate rendering:**
```powershell
.venv\Scripts\python.exe -m mkdocs serve
```

---

## License Header

All `napt/**/*.py` files require before docstring:

```python
# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

**Not required:** `tests/`, generated files. **Copyright year:** Always 2025.

**File order:** Shebang (if needed) → License → Module docstring → Imports → Code

---

## Exceptions

| Exception | Use For |
|-----------|---------|
| `ConfigError` | Recipe/YAML errors, missing fields, invalid config |
| `NetworkError` | HTTP failures, API errors, download issues |
| `PackagingError` | PSADT errors, MSI extraction, build failures |

**Public API / user-facing:** Use custom exceptions. **Private helpers / bugs:** Use built-in.

**Always chain:** `raise ConfigError(...) from err`

**Creating new types:** Only if existing types don't fit. Define in `napt/exceptions.py`. Include clear docstring explaining when to use.

---

## results.py Scope

`napt/results.py` is for **public API return types only** (`DiscoverResult`, `BuildResult`, `PackageResult`, `ValidationResult`).

Domain types and internal types stay co-located with their logic.

---

## Documentation

Update docs when code changes affect user-facing behavior.

| File | Purpose |
|------|---------|
| **index.md** | Landing page (synced to README.md) |
| **quick-start.md** | Installation, basic commands |
| **user-guide.md** | Full reference |
| **common-tasks.md** | Copy-paste workflows |
| **recipe-reference.md** | Complete recipe schema |

**README.md sync:** ONE-WAY from index.md. Transform relative links to full URLs.

**What to update:** New feature → user-guide, common-tasks, changelog. CLI change → same. Recipe schema → recipe-reference, common-tasks, changelog.

**Formatting:** Use sentence case for headings. One sentence per line in source. Wrap at 80 chars for prose.

**Validate:** Run `mkdocs serve` before committing doc changes.

---

## Recipe Schema Changes

When adding new recipe fields or modifying the YAML schema:

### 1. Update Validation

Add field to schema in `napt/validation.py`:

```python
_INSTALLED_CHECK_FIELDS: dict[str, tuple[type, list[str] | None, str]] = {
    "new_field": (str, ["value1", "value2"], "field description"),
    # type, allowed_values (or None), description
}
```

### 2. Document in recipe-reference.md

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

### 3. Update Defaults (if needed)

**Deciding where the default lives:**

| Question | Yes | No |
|----------|-----|----|
| Would an org realistically set this the same way across all/most recipes? | → `DEFAULT_CONFIG` + `ORG_YAML_TEMPLATE` | → inline fallback in code |

Examples:
- `log_format: "cmtrace"` — an org-wide logging policy, goes in `DEFAULT_CONFIG`
- `override_msi_display_name: false` — MSI-specific per-app behavior, stays inline

Per-recipe optional fields with inline defaults should be documented in `recipe-reference.md`, not in `DEFAULT_CONFIG` or `ORG_YAML_TEMPLATE`. The config hierarchy (org → vendor → recipe) lets users override any field at any level, but `DEFAULT_CONFIG` and `ORG_YAML_TEMPLATE` should only expose settings that make sense as org-wide policy.

If the field belongs in `DEFAULT_CONFIG`, update **both** dicts in `napt/config/defaults.py`:

1. Add to `DEFAULT_CONFIG` dict (the authoritative code defaults):
```python
DEFAULT_CONFIG = {
    "defaults": {
        "section": {
            "new_field": "default_value",
        },
    },
}
```

2. Add to `ORG_YAML_TEMPLATE` (the commented template for `napt init`):
```python
ORG_YAML_TEMPLATE = """
  # section:
  #   new_field: "default_value"  # Comment explaining purpose
"""
```

A test (`test_org_yaml_template_covers_all_sections`) validates that all sections in `DEFAULT_CONFIG` are mentioned in `ORG_YAML_TEMPLATE`.

### 4. Verify Implementation

Check these files to ensure the field is actually used:
- Search codebase: `grep -r "new_field" napt/`
- Verify it's read from config in relevant modules
- Check if field exists in defaults but isn't used (planned feature)

### 5. Update Examples

Add field to example recipes in `docs/common-tasks.md` if it's commonly used, or note it as optional in relevant strategy examples.

**Important:** All documented fields should either:
- Be validated in `validation.py` AND used in the code
- Be clearly marked as planned/future functionality
- Be removed if no longer needed

---

## Git & Releases

See `docs/branching.md` for full workflow. PR template at `.github/PULL_REQUEST_TEMPLATE.md`. GitHub CLI (`gh`) is available.

**Commits:** `type: subject` (feat, fix, docs, refactor, test, chore, perf). Under 50 chars, imperative, capitalized, no period.

**Branches:** `type/description-in-lowercase`

**PRs:** Title in conventional commit format. Use `gh pr create` to create PRs from CLI. PR descriptions should describe what changed and why, not include setup instructions or how-to guides.

### Release Workflow

[Semver 2.0.0](https://semver.org/spec/v2.0.0.html), no "v" prefix.

**Pre-release checklist:**
- [ ] Version updated in `pyproject.toml`
- [ ] Version updated in `napt/__init__.py`
- [ ] `docs/changelog.md` updated following [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
- [ ] `docs/changelog.md` has `[Unreleased]` section ready for next version
- [ ] All tests passing
- [ ] PR merged to main
- [ ] Git tag created and pushed

**Release steps:**
1. Create PR `chore/prepare-release-X.Y.Z` updating versions and changelog
2. Squash and merge
3. Tag: `git tag -a X.Y.Z -m "Release X.Y.Z"` then `git push origin X.Y.Z`
4. Create release: `gh release create X.Y.Z --title "NAPT X.Y.Z" --body "..."`

### Release Notes Template

**Title:** `NAPT {version}` (e.g., "NAPT 0.3.0")

**Required sections (in order):**
1. **Hero statement** - One sentence describing the release theme
2. **⚠️ Breaking Changes** - With migration notes (omit if none)
3. **✨ What's New** - Features from changelog, grouped by category
4. **🐛 Bug Fixes** - Important fixes (omit if none)
5. **🔗 Links** - Quick start, full changelog, documentation

**Optional sections:**
- **🚀 Quick Start** - Code examples for major new capabilities
- **📦 What You Can Do Now** - Workflow checklist (for major releases)

**Emoji categories for features:**
- 🔨 Build & Packaging
- 🔍 Discovery
- 📋 Recipes/Configuration

**Writing style:**
- Use active voice and present tense
- Be concise - summarize changelog, don't copy verbatim
- Include code examples for major features
- Highlight breaking changes clearly with migration instructions

**What NOT to include:**
- Internal refactorings (unless user-facing)
- Trivial fixes (unless security/critical)
- Work-in-progress features
- Overly technical implementation details

**Links to include:**
- [Quick Start Guide](https://rogercibrian.github.io/notapkgtool/quick-start/)
- [Full Changelog](https://rogercibrian.github.io/notapkgtool/changelog/)
- [Documentation](https://rogercibrian.github.io/notapkgtool/)
- [Sample Recipes](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)

---

## Changelog

Follow [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Focus on user impact, not implementation.

```markdown
## [Unreleased]

### Added
- **Feature Name** - What users can now do

### Changed
- **BREAKING: Change** - Migration path
    - Sub-item (4-space indent)

### Fixed
- Fixed symptom description
```

- Breaking changes: prefix `**BREAKING:**`
- One feature = one bullet
- Don't include: test updates, refactors without user impact

**On release:** Move items from `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`. Add comparison link at bottom.

---

## Roadmap

Update `docs/roadmap.md` when user mentions deferred features ("add to roadmap", "let's do this later").

```markdown
### Feature Name

**Status:** 💡 Idea
**Complexity:** Low | Medium | High | Very High
**Value:** Low | Medium | High | Very High

**Description:** What problem it solves.
**Benefits:** Why we'd want this.
```

Status progression: 💡 Idea → 🔬 Investigating → 📋 Ready → 🚧 In Progress → ✅ Completed

**Categories:** Group by: Discovery, Packaging, Deployment, CLI, Developer Experience.

**Don't add:** Bug reports (use issues), small enhancements (just do them), vague ideas without clear value.

---

## Logging Levels

| Method | When to use |
|--------|-------------|
| `logger.step(n, total, msg)` | Major pipeline stages (always visible) |
| `logger.info(prefix, msg)` | Notable events: skipping a step for a known reason, replacing an artifact, key IDs returned by external systems |
| `logger.warning(prefix, msg)` | Something unexpected but recoverable; user should be aware |
| `logger.verbose(prefix, msg)` | Implementation detail: exact file paths, intermediate values, internal state |
| `logger.debug(prefix, msg)` | Raw data dumps, backend selection attempts, very granular traces |

**`info` vs `verbose` rule of thumb:**

- "What happened?" (high-level outcome or decision) → `info`
- "How did it happen?" (implementation detail) → `verbose`

Examples:
- `"Version unchanged, using cached file"` → `info` (step was skipped)
- `"Cached ETag: abc123"` → `verbose` (internal state detail)
- `"Created Intune app: <id>"` → `info` (key result from external system)
- `"Content version: <cv_id>"` → `verbose` (intermediate internal ID)
- `"Downloading PSADT 4.1.7..."` → `info` (network action the user should see)
- `"Copying file: PSAppDeployToolkit/"` → `verbose` (internal file operation)

---

## Console Output

Use ASCII-only in console output. Windows (cp1252, cp437) causes `UnicodeEncodeError` with Unicode.

**Avoid:** ✓ ✔ ✗ ✘ ⚠️ → ← • ●

**Alternatives:** `[OK]`, `[FAIL]`, `[WARNING]`, `->`, `-`

**Applies to:** print(), logging, CLI output. **Not:** docs, JSON/YAML, comments.

---

## PSADT Reference

For PSAppDeployToolkit work, reference: `.claude_context/PSADT Reference Documentation 11.5.25/`

134+ functions, deployment concepts, config settings, exit codes. Covers v3.10.2, v4.0.0, latest.
