# Contributing to NAPT

Thank you for your interest in contributing to NAPT! This guide will help you get started.

## Getting Started

### Development Setup

```bash
# Clone and install with dev dependencies
git clone https://github.com/RogerCibrian/notapkgtool.git
cd notapkgtool
poetry install
poetry shell

# Verify installation
napt --version
```

### Running Tests

```bash
# Run all tests
poetry run pytest tests/

# Run only unit tests (fast)
poetry run pytest tests/ -m "not integration"

# Run with coverage
poetry run pytest tests/ --cov=notapkgtool --cov-report=html
```

### Code Quality

```bash
# Format code
poetry run black notapkgtool/ tests/

# Fix linting issues
poetry run ruff check --fix notapkgtool/ tests/

# Check types (if using mypy)
poetry run mypy notapkgtool/
```

## Branching Strategy

NAPT uses **GitHub Flow** - a simple, branch-based workflow that keeps `main` always deployable.

### Core Principles

1. **`main` branch is always stable** - Production-ready code only
2. **Feature branches for all work** - Every change starts from a branch
3. **Pull Requests for review** - All changes reviewed before merging
4. **Merge frequently** - Keep branches short-lived (< 1 week ideal)

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

**Naming Rules:**

- Use lowercase with hyphens
- Be descriptive but concise (3-6 words)
- Avoid generic names like `fix-bug` or `updates`
- No issue numbers in branch names

### Workflow

#### Starting New Work

```bash
# Always start from updated main
git checkout main
git pull origin main

# Create your feature branch
git checkout -b feature/your-feature-name
```

#### During Development

```bash
# Make changes, commit frequently
git add .
git commit -m "feat: add your feature"

# Push your branch
git push origin feature/your-feature-name
```

#### Creating a Pull Request

1. Push your branch to GitHub

2. Create a Pull Request on GitHub

3. Fill out the description with what the PR does, why the change is needed, and how it was tested

4. Request review from maintainers

5. Address any feedback

#### After Merge

```bash
# Update your local main
git checkout main
git pull origin main

# Delete your local feature branch
git branch -d feature/your-feature-name
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

## Code Guidelines

### Documentation Standards

All code must include:

1. **Module-level docstrings** - Explain purpose, features, and design decisions

2. **Function docstrings** - Use Google-style format with summary, Args, Returns, Raises, and Example sections

3. **Type annotations** - Full coverage for public APIs

4. **Comments** - Explain "why" not "what"

### Code Style

- **Formatting**: Use Black (line length 88)
- **Linting**: Pass Ruff checks
- **Type hints**: Modern Python 3.11+ syntax (`X | None`, not `Optional[X]`)
- **Import order**:
  1. `from __future__ import annotations` (if needed)
  2. Standard library
  3. Third-party packages
  4. First-party (NAPT) imports

### Testing Requirements

When adding new code:

1. **Write tests** - All new features must have tests
2. **Mock external dependencies** - Use requests-mock for HTTP, mock filesystem operations
3. **Test error cases** - Not just happy paths
4. **Use fixtures** - Leverage existing fixtures in `conftest.py`
5. **Keep tests fast** - Unit tests should run in milliseconds
6. **Mark integration tests** - Use `@pytest.mark.integration` for tests with real dependencies

### Design Principles

When contributing code:

1. **Follow existing patterns** - Use the same style and structure as existing code
2. **Chain exceptions** - Use `raise ... from err` for better debugging
3. **Return structured data** - Functions return dicts/dataclasses for testing
4. **Single responsibility** - Each function does one thing well
5. **Document design decisions** - Explain "why" in docstrings
6. **Test cross-platform** - Ensure Linux/Windows/macOS compatibility

## Pull Request Guidelines

### Before Submitting

- [ ] Code follows existing patterns and conventions
- [ ] All functions have comprehensive docstrings
- [ ] Type annotations are included
- [ ] Tests are added for new features
- [ ] All tests pass (`poetry run pytest tests/`)
- [ ] Code is formatted (`poetry run black notapkgtool/`)
- [ ] Linting passes (`poetry run ruff check --fix notapkgtool/`)
- [ ] Documentation is updated (README.md, docs/ if needed)

### PR Description Template

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

## Questions or Issues?

- **Questions**: Open a GitHub Discussion
- **Bug Reports**: Open a GitHub Issue with:
  - NAPT version (`napt --version`)
  - Python version
  - Platform (Windows/Linux/macOS)
  - Recipe file (or minimal example)
  - Error message and traceback
  - Steps to reproduce

## License

By contributing, you agree that your contributions will be licensed under the GNU General Public License v3.0.

