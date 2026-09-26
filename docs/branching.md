# Branching strategy

This is the maintainer's workflow; see [Contributing](contributing.md) for how
to propose changes (code contributions are not accepted before 1.0).

NAPT uses GitHub Flow: every change goes through a branch and a squash-merged
pull request into `main`.

## Core principles

1. **`main` passes lint, type checks, and tests**
2. **Feature branches for all work** - Every change starts from a branch
3. **Pull Requests for review** - All changes reviewed before merging

## Quick start

### 1. Start new work

```bash
# Always start from updated main
git checkout main
git pull origin main

# Create your feature branch
git checkout -b feat/your-feature-name
```

### 2. During development

```bash
# Make changes, commit frequently
git add .
git commit -m "feat: Add your feature"

# Push your branch
git push origin feat/your-feature-name
```

### 3. Create pull request

1. Create a Pull Request on GitHub
2. Fill out the description using the [PR template](#pull-request-process)
3. Request review from maintainers
4. Address any feedback

### 4. After merge

```bash
# Update your local main
git checkout main
git pull origin main

# Delete your local feature branch
git branch -d feat/your-feature-name

# Remote branch is usually auto-deleted by GitHub
```

## Branch management

### Branch structure

```
main (always deployable)
├── feat/add-rpm-support
├── fix/version-parsing
├── docs/update-installation-guide
└── refactor/simplify-config-loader
```

### Branch naming convention

The prefix is the conventional commit type the PR will squash to:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat/` | New features or enhancements | `feat/add-rpm-support` |
| `fix/` | Bug fixes | `fix/version-parsing` |
| `docs/` | Documentation updates | `docs/update-installation-guide` |
| `refactor/` | Code improvements (no behavior change) | `refactor/simplify-config-loader` |
| `test/` | Test additions/improvements | `test/add-integration-tests` |
| `chore/` | Maintenance tasks | `chore/update-dependencies` |
| `perf/` | Performance improvements | `perf/parallel-downloads` |

### Naming rules

- Use lowercase with hyphens
- Be descriptive but concise (3-6 words)
- Avoid generic names like `fix-bug` or `updates`
- No issue numbers in branch names (use commit messages instead)

**Good examples:**
```
feat/add-exe-version-extraction
fix/download-resume-logic
docs/add-cross-platform-examples
refactor/simplify-config-loader
```

**Bad examples:**
```
my-branch              # No type prefix
feat/stuff             # Not descriptive
Feat/My_Branch         # Wrong case
fix-bug                # Too generic
```

## Commit guidelines

### Commit message format

Commit messages use conventional commit format:

```
<type>: <description>

[optional body]
```

### Commit types

| Type | Purpose | Example |
|------|---------|---------|
| `feat` | New feature | `feat: Add EXE version extraction` |
| `fix` | Bug fix | `fix: Correct version comparison logic` |
| `docs` | Documentation | `docs: Update installation instructions` |
| `refactor` | Code improvement | `refactor: Simplify config loading` |
| `test` | Tests | `test: Add tests for MSI extraction` |
| `chore` | Maintenance | `chore: Update Poetry dependencies` |
| `perf` | Performance | `perf: Optimize version comparison` |

### Rules

- Use imperative mood: "add" not "added" or "adds"
- Keep subject line under 50 characters
- Capitalize subject line
- No period at end of subject
- Separate subject from body with blank line

**Good examples:**
```bash
git commit -m "feat: Add RPM version extraction support"
git commit -m "fix: Handle missing ETag headers gracefully"
git commit -m "docs: Add examples for Linux MSI extraction"
```

**Bad examples:**
```bash
git commit -m "added stuff"           # Not descriptive
git commit -m "Fix bug"               # No type prefix
git commit -m "WIP"                   # Too vague
```

## Pull request process

When creating a PR, the
[PR template](https://github.com/RogerCibrian/notapkgtool/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
auto-populates with sections for Description, Motivation, Changes, Testing,
and Checklist.

## Merge strategy

NAPT uses **squash and merge** for every Pull Request, including release
PRs, so `main` gets one clean, conventional commit per change instead of
every WIP commit from the branch.

### Merging

When merging on GitHub:
1. Click "Squash and merge"
2. Edit the commit message to follow conventional commit format
3. Summarize all changes in the commit body
4. Reference any issues with `Closes #XX`

**Example:**
```
fix: Keep retained releases in order after a rollback

- A displaced release now becomes the newest retained entry
- Publishing a release removes it from the retained list

Closes #42
```

Release PRs are no exception: `/release` makes a single
`chore: Prepare release X.Y.Z` commit (version bump plus changelog
promotion), and that squashes like any other PR.

### Tips

- Don't worry about messy commits in your branch; they'll be squashed
- The PR title becomes the squash subject; the default body is the branch's
  commit messages, so replace it with a summary when merging (see
  [Merging](#merging), step 3)
- Use conventional commit prefixes in PR titles for easy squashing
- If you accidentally use wrong merge method, you can revert and redo

## Scenarios

### Multiple related changes

If changes are closely related, keep in one branch:
```bash
feat/add-exe-support
  ├── Add EXE parsing module
  ├── Add tests
  └── Update documentation
```

If changes are independent, use separate branches:
```bash
feat/add-exe-support
feat/add-rpm-support
```

### Long-running features

For features taking multiple days/weeks:
1. Keep branch updated with `main` regularly
2. Break into smaller PRs if possible
3. Use draft PRs to show progress

### Urgent hotfixes

For critical production issues, branch from `main` as usual, then fix,
test, and push:
```bash
git commit -am "fix: Patch security vulnerability"
git push origin fix/security-vulnerability
```

## Best practices & quality checks

### Do

- Create small, focused branches with single purpose
- Commit early and often with clear messages
- Keep branches short-lived (merge within 1 week)
- Run the full check sequence before committing: `ruff check --fix`,
  `black`, `pyright`, `vulture`, then `pytest tests/` (the `/ship` skill
  runs all of these in order)
- Update branch with `main` if it's behind
- Delete branches after merging

### Don't

- Never commit directly to `main`
- Don't force push shared branches
- Don't mix unrelated changes in one PR
