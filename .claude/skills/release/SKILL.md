---
name: release
description: Prepare and ship a NAPT release. Phase 1 opens the release PR (version bumps + changelog promotion). Phase 2 (after merge) tags and publishes the GitHub release. Detects phase automatically.
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git *) Bash(*python* -m *) Bash(gh *) Read Edit Write Glob Grep
argument-hint: "version: X.Y.Z"
---

You are preparing a NAPT release. Semver (no `v` prefix). Follow every step in order.

## Step 1: Validate argument and detect phase

The user passes the target version as `X.Y.Z`. If absent, ask before proceeding.

Phase detection keys off `origin/main`, not your current checkout — both phases operate
on `origin/main` regardless of what you have checked out, so the branch you are standing
on never affects the release. Check state:
- `git fetch origin` — refresh remote refs first.
- `git tag -l X.Y.Z` — does the tag already exist? If yes, stop — release already published.
- `git show origin/main:pyproject.toml` — read `version` under `[project]`.

**Phase 2 (tag and publish):** Tag does not exist and the pyproject version on
`origin/main` is already `X.Y.Z` (the release PR was squash-merged). This detection holds
even if unrelated commits landed on main after the merge — Phase 2 locates the exact
release commit to tag.
**Phase 1 (open release PR):** Tag does not exist and the version is anything else.

Report which phase you detected before proceeding.

## Phase 1: Open the release PR

The release must be cut from a clean `main`, never from whatever branch you happen to be
on. Forking the branch from `origin/main` guarantees the PR diff contains only the version
bump and changelog promotion — nothing from an unrelated feature branch can leak in.

1. **Verify clean working tree.** Run `git status`. If there are uncommitted changes, stop
   and ask the user how to handle them — switching branches would carry or lose them.

2. **Check `[Unreleased]` has content.** Read it from the release base, not your checkout:
   `git show origin/main:docs/changelog.md`. If the `[Unreleased]` section is empty, stop —
   there is nothing to release. Checking before creating the branch means an abort here
   leaves nothing behind.

3. **Create the release branch from latest main.** You already ran `git fetch origin` in
   Step 1.
   - Guard: `git rev-parse --verify chore/prepare-release-X.Y.Z` and
     `git ls-remote --exit-code --heads origin chore/prepare-release-X.Y.Z`. If either
     succeeds (the branch already exists locally or on the remote), stop and report — a
     prior Phase 1 run is in flight; don't clobber it.
   - `git checkout -b chore/prepare-release-X.Y.Z origin/main`

   This forks from the current tip of `origin/main` no matter which branch was checked out,
   so all remaining steps operate on a clean release base.

4. **Run lint and tests** sequentially:
   ```
   .venv/Scripts/python.exe -m ruff check napt/ tests/
   .venv/Scripts/python.exe -m pytest tests/ -q
   ```
   If anything fails, stop and report. Do not continue.

5. **Bump version in two places** — both must match exactly:
   - `pyproject.toml` → `version = "X.Y.Z"` under `[project]`
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
   Cuts the X.Y.Z release.

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

   Substitute `X.Y.Z` with the real version and `YYYY-MM-DD` with today's date in the heredoc before running. Pull the bullet content for the **Changes** section from the actual `[X.Y.Z]` changelog block — replace the boilerplate above with one line per real bullet if there are notable user-facing changes worth surfacing in the PR body. The PR body describes what changed and why only — no workflow instructions (e.g. "squash-merge this, then run X"); those belong in your report to the user, not the PR.

9. **Report PR URL.** Tell the user to squash-merge, then re-run `/release X.Y.Z` for Phase 2.

## Phase 2: Tag and publish

Phase 2 never touches your checkout — no pull, no checkout, no branch switch. Everything
reads from `origin/main` (already fetched in Step 1) and the tag is created directly on
the release commit, so it works from whatever branch you happen to be standing on.

1. **Locate the release commit.** Find the squash-merge of the release PR:
   `git log origin/main --format="%H %s" -20` and take the most recent commit whose
   subject starts with `chore: Prepare release X.Y.Z`. If none is found, stop and report —
   the merge subject may have been edited at merge time; ask the user which commit to tag.

2. **Verify version files at that commit.** `git show <sha>:pyproject.toml` and
   `git show <sha>:napt/__init__.py` must both show X.Y.Z. If not, stop and report.

3. **Tag the release commit and push the tag:**
   ```
   git tag -a X.Y.Z <sha> -m "Release X.Y.Z"
   git push origin X.Y.Z
   ```
   Tagging `<sha>` directly — not HEAD, not the tip of main — keeps the tag exact even if
   other commits landed on main after the release PR merged.

4. **Build release notes** following the template below. Read the `[X.Y.Z]` section from
   `git show <sha>:docs/changelog.md` for source content.

5. **Create the GitHub release.** `gh release create` has no `--body` flag — write the
   notes to a file and pass it with `-F` (this also avoids heredoc quoting pitfalls).
   `--verify-tag` aborts if the tag isn't already on the remote, which it always is by
   this step.
   ```
   # Write the notes to a temp file first (e.g. via the Write tool), then:
   gh release create X.Y.Z --title "NAPT X.Y.Z" --verify-tag --latest -F <notes-file>
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
