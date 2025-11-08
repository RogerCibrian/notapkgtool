# Branching Strategy

NAPT uses **GitHub Flow** - a simple, branch-based workflow that keeps `main` always deployable.

## Core Principles

1. **`main` branch is always stable** - Production-ready code only
2. **Feature branches for all work** - Every change starts from a branch
3. **Pull Requests for review** - All changes reviewed before merging
4. **Merge frequently** - Keep branches short-lived (< 1 week ideal)

## Branch Structure

```
main (always deployable)
├── feature/add-rpm-support
├── bugfix/fix-version-parsing
├── docs/update-installation-guide
└── refactor/simplify-config-loader
```

## Branch Naming Convention

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

## Workflow

### Starting New Work

```bash
# Always start from updated main
git checkout main
git pull origin main

# Create your feature branch
git checkout -b feature/your-feature-name
```

### During Development

```bash
# Make changes, commit frequently
git add .
git commit -m "feat: add your feature"

# Push your branch
git push origin feature/your-feature-name
```

### Creating a Pull Request

1. Push your branch to GitHub
2. Create a Pull Request on GitHub
3. Fill out the description with:
   - What the PR does
   - Why the change is needed
   - How it was tested
4. Request review from maintainers
5. Address any feedback

### After Merge

```bash
# Update your local main
git checkout main
git pull origin main

# Delete your local feature branch
git branch -d feature/your-feature-name

# Remote branch is usually auto-deleted by GitHub
```

## Commit Message Format

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

## Best Practices

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

## Quality Checks

Before creating a Pull Request, ensure:

```bash
# Run tests
pytest tests/

# Format code
black notapkgtool/

# Check linting
ruff check notapkgtool/

# Run all checks at once
pytest tests/ && black notapkgtool/ && ruff check notapkgtool/
```

## Handling Merge Conflicts

If your branch conflicts with `main`:

```bash
# Update main
git checkout main
git pull origin main

# Switch back to your branch
git checkout feature/your-feature

# Merge main into your branch
git merge main

# Resolve conflicts in your editor
# Look for <<<<<<< markers

# After resolving, stage the files
git add path/to/resolved/file.py

# Complete the merge
git commit

# Push the updated branch
git push origin feature/your-feature
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

## Versioning and Releases

### Version Numbering

NAPT follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html):

- **MAJOR** (e.g., 1.0.0) - Incompatible API changes
- **MINOR** (e.g., 0.2.0) - New functionality (backward compatible)
- **PATCH** (e.g., 0.2.1) - Bug fixes (backward compatible)

**Note**: No "v" prefix - use `0.2.0` NOT `v0.2.0`

### Pre-Release Checklist

Before creating a release:

- [ ] All feature work merged to `main`
- [ ] Version updated in `pyproject.toml`
- [ ] Version updated in `notapkgtool/__init__.py`
- [ ] `docs/changelog.md` updated with all changes following [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
- [ ] `docs/changelog.md` has `[Unreleased]` section ready for next version
- [ ] Documentation updated (README, DOCUMENTATION, etc.)
- [ ] All tests passing
- [ ] Sample recipes tested end-to-end

### Release Process

#### 1. Prepare Release PR

Create a dedicated PR for the version bump:

```bash
git checkout main
git pull origin main
git checkout -b chore/prepare-release-0.x.0

# Update versions
# Edit pyproject.toml: version = "0.x.0"
# Edit notapkgtool/__init__.py: __version__ = "0.x.0"

# Update docs/changelog.md
# - Change [Unreleased] to [0.x.0] - YYYY-MM-DD
# - Add new [Unreleased] section at top
# - Update version comparison links

git add pyproject.toml notapkgtool/__init__.py docs/changelog.md
git commit -m "chore: prepare release 0.x.0"
git push origin chore/prepare-release-0.x.0
```

**PR Title**: `chore: prepare release 0.x.0`

**PR Description**: Brief summary of release highlights and link to docs/changelog.md

#### 2. Merge Release PR

After review and approval, merge the PR to `main` using **squash and merge**.

#### 3. Create and Push Git Tag

```bash
git checkout main
git pull origin main
git tag -a 0.x.0 -m "Release 0.x.0"
git push origin 0.x.0
```

#### 4. Create GitHub Release

Go to https://github.com/RogerCibrian/notapkgtool/releases/new

**Tag**: Select the tag you just pushed (e.g., `0.x.0`)

**Release Title**: `NAPT {version}`

Example: `NAPT 0.2.0`

**Release Description**: Follow the template in `.cursor/rules/napt-releases.mdc`

### Creating GitHub Releases

#### Release Title Format

```
NAPT {version}
```

Examples:
- `NAPT 0.2.0`
- `NAPT 0.3.0`
- `NAPT 1.0.0`

#### Release Description Template

Use this structure for consistency:

```markdown
# 🎉 NAPT {version} - {Feature Summary}

{One sentence hero statement describing the release}

## ✨ What's New

### 🔨 {Category Name}

- **{Feature Name}** with `command` details
  - Bullet point details
  - More details

### 🔍 {Another Category}

{Continue for all major features...}

## 🚀 Quick Start

```bash
# Show new commands or updated workflows
napt command args
```

## 📦 What You Can Do Now

Workflow checklist:
1. ✅ {Step 1}
2. ✅ {Step 2}
3. 🚧 {Coming soon}

## ⚠️ Breaking Changes

> **Note**: {Context about breaking changes policy}

- **{Change description}** - {Migration instructions}

## 🐛 Bug Fixes

- {Fix description}
- {Another fix}

## 📊 Stats

- **X files changed**: X insertions(+), X deletions(-)
- **New modules**: X
- **Test coverage**: {Coverage info}

## 🔗 Links

- **Full Changelog**: {Link to docs/changelog.md}
- **Documentation**: {Link to https://rogercibrian.github.io/notapkgtool}
- **Roadmap**: {Link to docs/roadmap.md}
- **Sample Recipes**: {Link to recipes/}

## 🎯 What's Next ({next version})

- {Planned feature 1}
- {Planned feature 2}

---

**Requirements**: Python 3.11+, Windows/Linux/macOS

**Tested with**: 
- {App 1 and version}
- {App 2 and version}

**Install**: `pip install pyyaml requests`
```

#### Emoji Guide for Categories

Use these emojis for consistent categorization:

- 🔨 Build & Packaging
- 🔍 Discovery & Detection
- 🗄️ State Management
- 🧪 Testing Infrastructure
- 📋 Recipes & Configuration
- 📚 Documentation
- 🚀 Quick Start / Usage
- 📦 Capabilities / Workflow
- ⚠️ Breaking Changes / Warnings
- 🐛 Bug Fixes
- 📊 Statistics / Metrics
- 🔗 External Links
- 🎯 Roadmap / Future Plans
- ✨ Highlights (header)
- 🎉 Release Hero (title)

#### Content Guidelines

**Do Include**:
- All significant changes from docs/changelog.md
- Code examples for new commands
- Migration instructions for breaking changes
- Quick start guide updates
- Test coverage and quality metrics
- Links to full documentation
- "What you can do now" workflow
- Preview of next version features

**Don't Include**:
- Internal refactorings (unless visible impact)
- Trivial formatting changes
- Work-in-progress features
- Overly technical implementation details
- Every single bug fix (only notable ones)

#### Writing Style

- **Active voice**: "This release adds..." not "Added in this release..."
- **Present tense**: "This command creates..." not "This command will create..."
- **User-focused**: Emphasize benefits, not just features
- **Concise**: One sentence per bullet when possible
- **Scannable**: Use headers, bullets, and code blocks
- **Complete**: Include all info needed to understand changes

### Example Release (0.2.0)

See the 0.2.0 release for a complete example:
https://github.com/RogerCibrian/notapkgtool/releases/tag/0.2.0

Key elements:
- Clear feature categories with emojis
- Code examples showing new capabilities  
- Breaking changes highlighted with migration notes
- Stats showing scope of changes
- Links to detailed documentation
- Preview of what's coming next

### Post-Release

After creating the GitHub release:

1. **Announce** (if applicable):
   - Internal communication channels
   - Project discussion boards
   - Social media (if public release)

2. **Monitor**:
   - GitHub issues for bug reports
   - User feedback on new features
   - Update docs/roadmap.md based on feedback

3. **Prepare Next Version**:
   - Create `[Unreleased]` section in docs/changelog.md (if not already done)
   - Update docs/roadmap.md with next milestone
   - Start planning next feature set

### PyPI Publication (Future)

When ready to publish to PyPI:

```bash
poetry build
poetry publish
```

Ensure `pyproject.toml` metadata is complete before first publication.

## Common Scenarios

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

## Questions?

- Check the [Documentation Site](https://rogercibrian.github.io/notapkgtool) for technical details
- Check [README.md](README.md) for project overview
- Open an issue for questions or discussions

---

**Last Updated**: 2025-11-07
**Strategy**: GitHub Flow with Squash and Merge

