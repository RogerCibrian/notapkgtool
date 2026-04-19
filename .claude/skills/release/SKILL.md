---
name: release
description: Prepare and ship a NAPT release. Phase 1 opens the release PR (version bumps + changelog promotion). Phase 2 (after merge) tags and publishes the GitHub release. Detects phase automatically.
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git *) Bash(*python* -m *) Bash(gh *) Read Edit Glob Grep
argument-hint: "version: X.Y.Z"
---

You are preparing a NAPT release. Semver (no `v` prefix). Follow every step in order.

## Step 1: Validate argument and detect phase

The user passes the target version as `X.Y.Z`. If absent, ask before proceeding.

Check current state to decide which phase to run:
- `git tag -l X.Y.Z` — does the tag already exist? If yes, stop — release already published.
- `git branch --show-current` — current branch
- `git log -1 --format=%s` — last commit subject

**Phase 1 (open release PR):** Tag does not exist; we are on `main` or any non-release branch.
**Phase 2 (tag and publish):** Tag does not exist; we are on `main` and the last commit subject is `chore: Prepare release X.Y.Z` (i.e., the release PR was just squash-merged).

Report which phase you detected before proceeding.

## Phase 1: Open the release PR

1. **Verify clean state.** Run `git status`. If unstaged changes unrelated to the release exist, stop and ask the user how to handle them.

2. **Check `[Unreleased]` has content.** Read `docs/changelog.md`. If the `[Unreleased]` section is empty, stop — there is nothing to release.

3. **Run lint and tests** sequentially:
   ```
   .venv/Scripts/python.exe -m ruff check napt/ tests/
   .venv/Scripts/python.exe -m pytest tests/ -q
   ```
   If anything fails, stop and report. Do not continue.

4. **Create branch:** `git checkout -b chore/prepare-release-X.Y.Z`

5. **Bump version in two places** — both must match exactly:
   - `pyproject.toml` → `version = "X.Y.Z"` under `[tool.poetry]`
   - `napt/__init__.py` → `__version__ = "X.Y.Z"`

6. **Promote changelog** in `docs/changelog.md`:
   - Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (today's date in absolute form, not "today")
   - Insert a fresh empty `## [Unreleased]` section above it
   - Add a comparison link at the bottom of the file: `[X.Y.Z]: https://github.com/RogerCibrian/notapkgtool/compare/PREV...X.Y.Z` (PREV = the previous release tag)

7. **Stage and commit** specific files only:
   ```
   git add pyproject.toml napt/__init__.py docs/changelog.md
   git commit -m "chore: Prepare release X.Y.Z"
   ```

8. **Push and open PR.** Push the branch, then open the PR using the project template at `.github/PULL_REQUEST_TEMPLATE.md`. Read that file first and follow its sections (Description / Motivation / Changes / Testing / Checklist).

   ```
   git push -u origin chore/prepare-release-X.Y.Z
   gh pr create --title "chore: Prepare release X.Y.Z" --body "$(cat <<'EOF'
   ## Description
   Release PR for NAPT X.Y.Z. Bumps version in `pyproject.toml` and `napt/__init__.py`, promotes the `[Unreleased]` section of `docs/changelog.md` to `[X.Y.Z]`, and adds a fresh empty `[Unreleased]` section.

   ## Motivation
   Cuts the X.Y.Z release. Squash-merge this PR, then `/release X.Y.Z` again to tag and publish.

   ## Changes
   - Bump `pyproject.toml` version to X.Y.Z
   - Bump `napt/__init__.py` `__version__` to X.Y.Z
   - Promote `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` in `docs/changelog.md`
   - Add comparison link `[X.Y.Z]: ...compare/PREV...X.Y.Z`

   ## Testing
   - [x] Unit tests pass
   - [x] Integration tests pass (run via `pytest tests/`)
   - [x] Manual testing performed (n/a — release prep only, no code changes)

   ## Checklist
   - [x] Code follows project conventions
   - [x] Documentation updated (changelog promoted)
   - [x] Tests pass
   - [x] No linting errors
   EOF
   )"
   ```

   Substitute `X.Y.Z` with the real version and `YYYY-MM-DD` with today's date in the heredoc before running. Pull the bullet content for the **Changes** section from the actual `[X.Y.Z]` changelog block — replace the boilerplate above with one line per real bullet if there are notable user-facing changes worth surfacing in the PR body.

9. **Report PR URL.** Tell the user to squash-merge, then re-run `/release X.Y.Z` for Phase 2.

## Phase 2: Tag and publish

1. **Pull latest main:** `git pull origin main`

2. **Verify version files.** Read `pyproject.toml` and `napt/__init__.py` to confirm both show X.Y.Z. If not, stop and report.

3. **Tag and push the tag:**
   ```
   git tag -a X.Y.Z -m "Release X.Y.Z"
   git push origin X.Y.Z
   ```

4. **Build release notes** following the template below. Read the `[X.Y.Z]` section of `docs/changelog.md` for source content.

5. **Create the GitHub release:**
   ```
   gh release create X.Y.Z --title "NAPT X.Y.Z" --body "$(cat <<'EOF'
   <release notes here>
   EOF
   )"
   ```

6. **Report the release URL.**

## Release Notes Template

**Title:** `NAPT X.Y.Z`

**Required sections (in order):**
1. **Hero statement** — one sentence describing the release theme
2. **⚠️ Breaking Changes** — with migration notes (omit if none)
3. **✨ What's New** — features from changelog, grouped by category
4. **🐛 Bug Fixes** — important fixes (omit if none)
5. **🔗 Links** — quick start, full changelog, documentation

**Optional sections:**
- **🚀 Quick Start** — code examples for major new capabilities
- **📦 What You Can Do Now** — workflow checklist (for major releases)

**Emoji categories for features:**
- 🔨 Build & Packaging
- 🔍 Discovery
- 📋 Recipes / Configuration

**Writing style:**
- Active voice, present tense
- Concise — summarize the changelog, don't copy verbatim
- Include code examples for major features
- Highlight breaking changes clearly with migration instructions

**Don't include:**
- Internal refactorings (unless user-facing)
- Trivial fixes (unless security/critical)
- Work-in-progress features
- Overly technical implementation details

**Links to include (always):**
- [Quick Start Guide](https://rogercibrian.github.io/notapkgtool/quick-start/)
- [Full Changelog](https://rogercibrian.github.io/notapkgtool/changelog/)
- [Documentation](https://rogercibrian.github.io/notapkgtool/)
- [Sample Recipes](https://github.com/RogerCibrian/notapkgtool/tree/main/recipes)
