"""Post-edit hook: lint and format edited Python files in napt/ or tests/.

Reads the Claude Code PostToolUse JSON payload from stdin, extracts the
edited file path, and runs ruff --fix + black on it if it lives under
napt/ or tests/. Silent on success; never blocks the tool call.
"""

import json
import re
import subprocess
import sys

# The hook is launched with the project venv's interpreter, so reuse it. A
# relative ".venv/Scripts/python.exe" cannot be started by subprocess on
# Windows (CreateProcess rejects the forward slashes), which made this hook
# fail silently.
PY = sys.executable
TARGET = re.compile(r"[/\\](napt|tests)[/\\].*\.py$")


def main() -> int:
    """Runs ruff and black on the edited file if it is under napt/ or tests/."""
    try:
        # Read bytes, not text: the payload is UTF-8, and on Windows sys.stdin
        # decodes as cp1252, which garbles a non-ASCII file path.
        data = json.load(sys.stdin.buffer)
    except Exception:
        return 0

    path = (
        data.get("tool_response", {}).get("filePath")
        or data.get("tool_input", {}).get("file_path")
        or ""
    )
    if not path or not TARGET.search(path):
        return 0

    # F401 (unused import) is left unfixed: an edit often adds an import one
    # step before the code that uses it, and deleting it here would undo that.
    # `ruff check` still reports it.
    subprocess.run(
        [PY, "-m", "ruff", "check", "--fix", "--unfixable", "F401", path],
        capture_output=True,
    )
    subprocess.run(
        [PY, "-m", "black", "-q", path],
        capture_output=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
