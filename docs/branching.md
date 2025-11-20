# Branching Strategy

NAPT uses **GitHub Flow** - a simple, branch-based workflow that keeps `main` always deployable.

## Core Principles

1. **`main` branch is always stable** - Production-ready code only
2. **Feature branches for all work** - Every change starts from a branch
3. **Pull Requests for review** - All changes reviewed before merging
4. **Merge frequently** - Keep branches short-lived (< 1 week ideal)

## Quick Start

The most common workflow for making changes:

### 1. Start New Work

```bash
# Always start from updated main
git checkout main
git pull origin main

# Create your feature branch
git checkout -b feature/your-feature-name
```

### 2. During Development

```bash
# Make changes, commit frequently
git add .
git commit -m "feat: add your feature"

# Push your branch
git push origin feature/your-feature-name
```

### 3. Create Pull Request

1. Push your branch to GitHub
2. Create a Pull Request on GitHub
3. Fill out the description using the [PR template](#pull-request-description-template)
4. Request review from maintainers
5. Address any feedback

### 4. After Merge

```bash
# Update your local main
git checkout main
git pull origin main

# Delete your local feature branch
git branch -d feature/your-feature-name

# Remote branch is usually auto-deleted by GitHub
```

## Branch Management

### Branch Structure

```
main (always deployable)
├── feature/add-rpm-support
├── bugfix/fix-version-parsing
├── docs/update-installation-guide
└── refactor/simplify-config-loader
```

### Branch Naming Convention

Use descriptive names with type prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New features or enhancements | `feature/add-rpm-support` |
| `bugfix/` | Bug fixes | `bugfix/fix-version-parsing` |
| `docs/` | Documentation updates | `docs/update-installation-guide` |
| `refactor/` | Code improvements (no behavior change) | `refactor/simplify-config-loader` |
| `test/` | Test additions/improvements | `test/add-integration-tests` |
| `chore/` | Maintenance tasks | `chore/update-dependencies` |
| `hotfix/` | Urgent production fixes | `hotfix/security-patch` |

### Naming Rules

- Use lowercase with hyphens
- Be descriptive but concise (3-6 words)
- Avoid generic names like `fix-bug` or `updates`
- No issue numbers in branch names (use commit messages instead)

**Good Examples:**
```
feature/add-exe-version-extraction
bugfix/fix-download-resume-logic
docs/add-cross-platform-examples
refactor/simplify-config-loader
```

**Bad Examples:**
```
my-branch              # No type prefix
feature/stuff          # Not descriptive
Feature/My_Branch      # Wrong case
fix-bug                # Too generic
```

## Commit Guidelines

### Commit Message Format

Use conventional commit format for clarity:

```
<type>: <description>

[optional body]
```

### Commit Types

| Type | Purpose | Example |
|------|---------|---------|
| `feat` | New feature | `feat: add EXE version extraction` |
| `fix` | Bug fix | `fix: correct version comparison logic` |
| `docs` | Documentation | `docs: update installation instructions` |
| `refactor` | Code improvement | `refactor: simplify config loading` |
| `test` | Tests | `test: add tests for MSI extraction` |
| `chore` | Maintenance | `chore: update Poetry dependencies` |
| `perf` | Performance | `perf: optimize version comparison` |

### Commit Guidelines

- Use imperative mood: "add" not "added" or "adds"
- Keep subject line under 50 characters
- Capitalize subject line
- No period at end of subject
- Separate subject from body with blank line

**Good Examples:**
```bash
git commit -m "feat: add RPM version extraction support"
git commit -m "fix: handle missing ETag headers gracefully"
git commit -m "docs: add examples for Linux MSI extraction"
```

**Bad Examples:**
```bash
git commit -m "added stuff"           # Not descriptive
git commit -m "Fix bug"               # No type prefix
git commit -m "WIP"                   # Too vague
```

## Pull Request Process

### Pull Request Description Template

```markdown
## Description
Brief description of what this PR does.

## Motivation
Why is this change needed?

## Changes
- Bullet list of key changes
- Include any breaking changes

## Testing
How was this tested?
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Checklist
- [ ] Code follows project conventions
- [ ] Documentation updated
- [ ] Tests pass
- [ ] No linting errors
```

## Merge Strategy

**Default: Squash and Merge**

NAPT uses **squash and merge** for most Pull Requests to maintain a clean, readable history in `main`.

### Why Squash and Merge?

- ✅ **Clean history**: One commit per feature/fix in `main`
- ✅ **Conventional commits**: Each merge becomes a properly formatted commit
- ✅ **Easy rollback**: Revert entire features with one command
- ✅ **Better changelogs**: No noise from "WIP" or "fix typo" commits
- ✅ **Simple bisecting**: Each commit represents a complete, working change

### When to Use Each Strategy

**Squash and Merge (Default - 95% of PRs)**

Use for:
- Feature additions
- Bug fixes
- Documentation updates
- Refactoring
- Chores and maintenance

When merging on GitHub:
1. Click "Squash and merge"
2. Edit the commit message to follow conventional commit format
3. Summarize all changes in the commit body
4. Reference any issues with `Closes #XX`

**Example:**
```
feat: add RPM version extraction support

- Implement RPM ProductVersion parser using rpm-py-installer
- Add cross-platform support for RPM files (Linux/macOS)
- Add comprehensive test coverage with mock RPM files
- Update documentation with RPM examples

Closes #42
```

**Regular Merge (Exceptional Cases)**

Use only when:
- Multiple authors need attribution for distinct contributions
- Release PRs where version bump history should be preserved
- Large features with logically separate commits worth keeping

**Example scenarios:**
- Version bump PRs (preserve "bump version" + "update changelog" as separate commits)
- Community contributions with multiple meaningful commits
- Complex refactors where commit-by-commit history aids debugging

### Workflow

1. **Before creating PR**: Clean up your branch commits if needed
2. **During review**: Add commits normally (don't squash yet)
3. **When merging**: Use GitHub's "Squash and merge" button
4. **After merge**: Branch is auto-deleted, pull latest `main`

### Tips

- Don't worry about messy commits in your branch - they'll be squashed
- Focus on clear PR descriptions - they become the squash commit message
- Use conventional commit prefixes in PR titles for easy squashing
- If you accidentally use wrong merge method, you can revert and redo

## Troubleshooting & Scenarios


### Multiple Related Changes

If changes are closely related, keep in one branch:
```bash
feature/add-exe-support
  ├── Add EXE parsing module
  ├── Add tests
  └── Update documentation
```

If changes are independent, use separate branches:
```bash
feature/add-exe-support
feature/add-rpm-support
```

### Long-Running Features

For features taking multiple days/weeks:
1. Keep branch updated with `main` regularly
2. Break into smaller PRs if possible
3. Use draft PRs to show progress
4. Consider feature flags for incomplete features

### Urgent Hotfixes

For critical production issues:
```bash
# Branch from main
git checkout main
git pull origin main
git checkout -b hotfix/fix-security-vulnerability

# Fix, test, and push
git commit -am "fix: patch security vulnerability"
git push origin hotfix/fix-security-vulnerability

# Create PR with high priority
# Fast-track review and merge
```

## Best Practices & Quality Checks

### DO ✅

- Create small, focused branches with single purpose
- Commit early and often with clear messages
- Keep branches short-lived (merge within 1 week)
- Run tests before pushing (`pytest tests/`)
- Format code before committing (`black notapkgtool/`)
- Update branch with `main` if it's behind
- Delete branches after merging

### DON'T ❌

- Never commit directly to `main`
- Don't create long-lived feature branches
- Don't use generic branch/commit names
- Don't merge without tests passing
- Don't force push to shared branches
- Don't include unrelated changes in one PR

---

**Last Updated**: 2025-11-18

**Strategy**: GitHub Flow with Squash and Merge
