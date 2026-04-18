---
name: ship
description: Wrap up current work - lint, test, branch (if needed), update docs/changelog, commit, and create PR
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git *) Bash(*python* -m *) Bash(gh *) Read Edit Glob Grep
argument-hint: "commit type: feat|fix|refactor|docs|test|chore"
---

You are shipping the current work as a PR. Follow every step in order.

## Step 1: Assess current state

Run these in parallel:
- `git branch --show-current` to check if on a feature branch or main
- `git status` to see what's changed (never use -uall)
- `git diff --stat` to understand scope of changes

Tell the user what you found: branch name, number of files changed, and a
one-line summary of the changes.

## Step 2: Lint and format

Run these sequentially using the platform's Python path (`.venv/Scripts/python.exe`
on Windows, `.venv/bin/python` on macOS/Linux):
```
python -m ruff check --fix napt/ tests/
python -m black napt/ tests/
python -m ruff check napt/ tests/
```

If ruff or black made changes, tell the user what was fixed.
If any lint errors remain that --fix couldn't resolve, stop and report them.

## Step 3: Run tests

```
python -m pytest tests/ -q
```

Run the full test suite including integration tests. If tests fail, stop and
report the failures. Do not continue.

## Step 4: Create branch (if needed)

If already on a feature branch (not `main`), skip this step.

If on `main`:
1. Determine the commit type from the changes (feat, fix, refactor, docs,
   test, chore). If the user passed an argument, use that as the type.
2. Pick a descriptive branch name following docs/branching.md conventions:
   - Prefix: `feature/`, `bugfix/`, `docs/`, `refactor/`, `test/`, `chore/`
   - Lowercase with hyphens, 3-6 words, descriptive not generic
3. Create the branch: `git checkout -b <type>/<name>`
4. Tell the user the branch name you chose.

## Step 5: Update docs and changelog

Check whether any changes affect user-facing behavior by reviewing the diff.

If user-facing changes exist:
1. Read `docs/changelog.md`
2. Add entries under `[Unreleased]` following Keep a Changelog 1.1.0 format
   (Added/Changed/Fixed/Removed). Focus on user impact, not implementation.
3. Check if `docs/user-guide.md`, `docs/common-tasks.md`, or
   `docs/recipe-reference.md` need updates based on the CLAUDE.md rules.
   Update them if needed.

If changes are purely internal (refactor, test, chore with no user impact),
skip changelog and doc updates. Tell the user you skipped this and why.

## Step 6: Commit

1. Stage all relevant changed files by name (not `git add -A`). Never stage
   .env, credentials, or secrets files.
2. Write a commit message in conventional commit format per CLAUDE.md:
   - `type: Subject` (imperative, capitalized, under 50 chars, no period)
   - Use a HEREDOC for the message
3. Multiple commits are fine if it makes sense to separate them logically
   (e.g., a refactor commit + a feature commit, or code changes separate
   from doc updates). Use your judgment.
4. Commit.

## Step 7: Push and create PR

1. Push the branch: `git push -u origin <branch-name>`
2. Create the PR using `gh pr create` with:
   - Title in conventional commit format (same as commit subject)
   - Body following the PR template structure (Description, Motivation,
     Changes, Testing, Checklist). Use a HEREDOC for the body.
   - PR descriptions should describe what changed and why, not include
     setup instructions or how-to guides.
3. Report the PR URL to the user.
