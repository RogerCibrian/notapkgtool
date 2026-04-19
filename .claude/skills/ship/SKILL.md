---
name: ship
description: Wrap up current work - lint, test, branch (if needed), update docs/changelog, commit, and create PR
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git *) Bash(*python* -m *) Bash(gh *) Read Edit Glob Grep Agent
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

Run these sequentially:
```
.venv/Scripts/python.exe -m ruff check --fix napt/ tests/
.venv/Scripts/python.exe -m black napt/ tests/
.venv/Scripts/python.exe -m ruff check napt/ tests/
```

If ruff or black made changes, tell the user what was fixed.
If any lint errors remain that --fix couldn't resolve, stop and report them.

## Step 3: Run tests

```
.venv/Scripts/python.exe -m pytest tests/ -q
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

## Step 6: Run napt-reviewer

Invoke the `napt-reviewer` subagent via the Agent tool to review the full
branch delta against CLAUDE.md conventions, docs/changelog requirements, and
project principles (including forward-looking consequences).

- `subagent_type`: `napt-reviewer`
- `description`: "Review branch against CLAUDE.md"
- `prompt`: "Review the current branch against CLAUDE.md conventions. This
  is a pre-commit review — uncommitted changes in the working tree are part
  of what will ship. Use `git diff main` to capture the full delta including
  uncommitted changes. Report findings with severity and a final verdict."

**Echo the reviewer's full output verbatim** as your own text output before
doing anything else. The subagent's output renders as a collapsed box in the
terminal by default, so the user can't see findings without expanding it.
Repeating the output as main-thread text makes it visible inline. Preserve
the reviewer's severity grouping and final verdict line.

Then, based on the findings:

- **If the review is entirely clean** (no `[BLOCKING]`, no `[SUGGESTION]`,
  no `[NIT]`, and verdict is `ship`), continue to Step 7 without prompting.
- **If the reviewer returns any finding at any severity** — including
  `[NIT]` — STOP and ask the user how to proceed. Do not auto-fix, do not
  auto-commit, do not continue to Step 7. Ask the user per-finding or
  collectively: "How would you like to proceed — address any of these before
  committing, skip them, or override?" Wait for their direction.

Never attempt to fix findings on the user's behalf without explicit
instruction. The reviewer surfaces; the user decides — including on nits.

## Step 7: Commit

1. Stage all relevant changed files by name (not `git add -A`). Never stage
   .env, credentials, or secrets files.
2. Write a commit message in conventional commit format per CLAUDE.md:
   - `type: Subject` (imperative, capitalized, under 50 chars, no period)
   - Use a HEREDOC for the message
3. Multiple commits are fine if it makes sense to separate them logically
   (e.g., a refactor commit + a feature commit, or code changes separate
   from doc updates). Use your judgment.
4. Commit.

## Step 8: Push and create PR

1. Push the branch: `git push -u origin <branch-name>`
2. Create the PR using `gh pr create` with:
   - Title in conventional commit format (same as commit subject)
   - Body following the PR template structure (Description, Motivation,
     Changes, Testing, Checklist). Use a HEREDOC for the body.
   - PR descriptions should describe what changed and why, not include
     setup instructions or how-to guides.
3. Report the PR URL to the user.
