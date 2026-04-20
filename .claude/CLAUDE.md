# NAPT Project Rules

## Project Principles

**NAPT does:** Discovery, packaging, deployment, state management.

**NAPT does not:** Git operations, PR creation, CI/CD workflow logic. Don't add `--create-pr` flags or git commands.

**Audience — CLI tool, not a library:** NAPT is a CLI consumed via `napt <command>`. Write docstrings, examples, and architectural decisions for two audiences only:

1. **CLI users** — interact via `napt <command>`; never import NAPT in their own code.
2. **Contributors** — work inside this codebase.

Don't write framing like "third-party extension API," "implementing custom strategies in your project," or "as a library user." Code is organized for internal clarity and CLI ergonomics, not for external Python consumers. Public Python entry points (e.g. `discover_recipe`, `validate_recipe`) exist for testing and scripting but are not a stability contract — don't add backwards-compat shims, plugin systems, or extension hooks aimed at downstream Python users.

**No backward compatibility (pre-release):** Implement cleanest solutions directly. Remove deprecated code immediately. No migration paths or fallback logic. After v1.0.0, standard semver applies.

---

## Development Environment

- **Python:** 3.13.5
- **Virtual environment:** `.venv/`
- **Shell:** PowerShell 7

**Run Python tools directly:**
```powershell
.venv\Scripts\python.exe -m ruff check --fix napt/ tests/
.venv\Scripts\python.exe -m black napt/ tests/
.venv\Scripts\python.exe -m pytest tests/ -m "not integration"   # unit tests only (fast)
.venv\Scripts\python.exe -m pytest tests/                        # all tests including integration
```

**Integration tests** (`tests/integration/`) require network access and download real dependencies. They are marked `@pytest.mark.integration`. Run unit tests during development; run the full suite before opening a PR.

---

## Code Quality

Use **ruff** + **black**. Fix all errors before committing. Never ignore errors. Configuration is in `pyproject.toml`.

**Auto-formatting:** A `PostToolUse` hook (`.claude/hooks/lint_edited.py`) runs `ruff --fix` and `black` on every edit to `napt/**/*.py` and `tests/**/*.py`. Don't manually run the formatters on individual files after an Edit/Write — they've already been applied. The commands below are for bulk reformats and the final pre-commit `ruff check` verification.

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

**Cross-references:** Use Markdown reference links — `[Display Name][full.dotted.path]` — never Sphinx-style (`:class:`, `:func:`, `:meth:`, `:mod:`). Sphinx syntax renders as literal text in mkdocstrings. The short form `[Name][]` only works when `Name` is itself the full identifier; for project symbols always use the full dotted path. For stdlib types, don't link — wrap in double backticks (e.g. `` ``typing.Protocol`` ``).

**No meta-commentary in docstrings or code.** Describe the subject, not the writing. Skip defensive denials ("this is internal, not a public API"), syntax explanations ("the reference above uses the short form because..."), and any sentence that explains how you wrote rather than what the thing is.

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

**Auto-injection:** A `PreToolUse` hook (`.claude/hooks/check_license_header.py`) auto-prepends the header to `Write` calls on `napt/**/*.py` when it's missing. The hook is shebang-aware (inserts after the shebang line if present). No manual action needed.

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

When adding a new recipe field or modifying the YAML schema, run `/add-recipe-field <name>`. The skill walks validation (`napt/validation.py`), documentation (`docs/recipe-reference.md`), categorization (org-policy / strategy-specific / recipe-required / absent-means-skip / computed), and the per-category checklist.

---

## Git & Releases

See `docs/branching.md` for full workflow. PR template at `.github/PULL_REQUEST_TEMPLATE.md`. GitHub CLI (`gh`) is available.

**Commits:** `type: subject` (feat, fix, docs, refactor, test, chore, perf). Under 50 chars, imperative, capitalized, no period.

**Branches:** `type/description-in-lowercase`

**PRs:** Title in conventional commit format. Use `gh pr create` to create PRs from CLI. PR descriptions should describe what changed and why, not include setup instructions or how-to guides.

**Releases:** Run `/release X.Y.Z`. Phase 1 opens the release PR (version bumps in `pyproject.toml` + `napt/__init__.py`, changelog promotion). Phase 2 (after the PR is squash-merged) tags and publishes the GitHub release. The skill includes the release notes template ([Semver 2.0.0](https://semver.org/spec/v2.0.0.html), no `v` prefix).

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

When the user mentions deferred features ("add to roadmap", "let's do this later"), run `/roadmap`. The skill enforces the standard entry structure (Status / Complexity / Value / Description / Benefits / Prerequisites / Dependencies / Related), the status-progression vocabulary, and category placement (User-Facing Features / Code Quality & Validation / Technical Enhancements) in `docs/roadmap.md`.

---

## Logging Levels

| Method | When to use |
|--------|-------------|
| `logger.step(n, total, msg)` | Major pipeline stages (always visible) |
| `logger.info(prefix, msg)` | Notable events: skipping a step for a known reason, replacing an artifact, key IDs returned by external systems |
| `logger.warning(prefix, msg)` | Something unexpected but recoverable; user should be aware |
| `logger.progress(prefix, msg)` | Download/upload progress that overwrites the current line (always visible) |
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
