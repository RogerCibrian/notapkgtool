# Contributing to NAPT

Thank you for your interest in contributing to NAPT! This guide will help you get started.

## Getting Started

### Feature Ideas

Have an idea for NAPT? Check [docs/roadmap.md](roadmap.md) to see what's planned and add your suggestions to the appropriate category!

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

# Check docstring formatting
poetry run ruff check --select D notapkgtool/

# Check types (if using mypy)
poetry run mypy notapkgtool/
```

## Branching Strategy

NAPT uses **GitHub Flow** - a simple, branch-based workflow. See [branching.md](branching.md) for complete workflow details.

**Quick Summary:**
- Create feature branches from `main` (use prefixes: `feature/`, `bugfix/`, `docs/`)
- Make frequent, small commits with conventional commit messages
- Open Pull Requests for code review
- Merge to `main` when approved
- Keep `main` always stable and deployable

**Branch naming:** `feature/add-rpm-support`, `bugfix/fix-version-parsing`, `docs/update-guide`

**Commit format:** `<type>: <description>` where type is feat, fix, docs, refactor, test, chore, or perf

## Code Guidelines

### Python Docstring Standards

All Python code must follow **Google-style docstrings**:

**Module docstrings:**

- Brief summary + optional detailed description
- Use "Key Features" or "Key Advantages" bullet lists (with blank line before)
- Include Example section if helpful
- Avoid: schema dumps, workflow steps, package structure listings, migration notes

**Function docstrings:**

- One-line summary + optional details
- Standard sections: `Args:`, `Returns:`, `Raises:`, `Example:`, `Note:`
- Use `Example:` (singular, NEVER `Examples:` or `Usage Example:`)
- Use `Note:` (singular, NEVER `Notes:`)
- NO `>>>` doctest prompts - causes rendering issues
- ALL content after section headers MUST be indented 4 spaces
- Add blank line after section headers before content

**Type annotations:**

- Full coverage for public APIs
- Modern Python 3.11+ syntax (`X | None`, not `Optional[X]`)

### Markdown Documentation

When updating documentation in `docs/*.md`, follow the 3-tier structure:

**1. docs/index.md (Landing Page)**

- High-level overview only
- Simple diagrams (5-10 nodes, centered with `<div align="center">`)
- Link to deeper content, don't duplicate

**2. docs/quick-start.md (Quick Start)**

- Installation steps (pip first, then Poetry)
- Basic command examples with expected outputs
- Platform-specific requirements

**3. docs/user-guide.md (Comprehensive Guide)**

- Section order: Commands → Strategies → State → Configuration → Best Practices
- Technical depth appropriate here
- Detailed diagrams (can split complex ones)
- Performance comparisons and troubleshooting

**Key principle:** No redundancy - each piece of information lives in ONE appropriate place.

### Code Style

- **Formatting**: Use Black (line length 88)
- **Linting**: Pass Ruff checks (including docstring checks with `-select D`)
- **Type hints**: Modern Python 3.11+ syntax (`X | None`, not `Optional[X]`)
- **Import order**: Ruff automatically organizes imports:
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

Before creating a pull request, ensure:

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

