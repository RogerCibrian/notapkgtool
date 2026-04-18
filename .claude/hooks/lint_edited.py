"""Post-edit hook: lint and format edited Python files in napt/ or tests/.

Reads the Claude Code PostToolUse JSON payload from stdin, extracts the
edited file path, and runs ruff --fix + black on it if it lives under
napt/ or tests/. Silent on success; never blocks the tool call.
"""

import json
import re
import subprocess
import sys

PY = ".venv/Scripts/python.exe"
TARGET = re.compile(r"[/\\](napt|tests)[/\\].*\.py$")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    path = (
        data.get("tool_response", {}).get("filePath")
        or data.get("tool_input", {}).get("file_path")
        or ""
    )
    if not path or not TARGET.search(path):
        return 0

    subprocess.run(
        [PY, "-m", "ruff", "check", "--fix", path],
        capture_output=True,
    )
    subprocess.run(
        [PY, "-m", "black", "-q", path],
        capture_output=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
