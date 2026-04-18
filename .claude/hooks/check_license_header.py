"""Pre-Write hook: auto-prepend Apache 2.0 license header to napt/**/*.py.

Reads the Claude Code PreToolUse JSON payload from stdin. If the tool is
`Write` to a file under `napt/` (excluding `tests/`) and the content lacks
the Apache 2.0 marker, rewrite `tool_input.content` with the header
inserted before the module docstring (or after the shebang, if present).

Implementation note: uses `hookSpecificOutput.updatedInput` so the Write
proceeds with the normalized content. The model sees the tool succeed
normally — no wasted turn.
"""

import json
from pathlib import Path
import sys

LICENSE_MARKER = "Licensed under the Apache License, Version 2.0"

LICENSE_HEADER = """# Copyright 2025 Roger Cibrian
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."""


def needs_header(file_path: str, content: str) -> bool:
    if not file_path.endswith(".py"):
        return False
    parts = Path(file_path).parts
    if "napt" not in parts or "tests" in parts:
        return False
    return LICENSE_MARKER not in content


def prepend_header(content: str) -> str:
    """Insert LICENSE_HEADER after the shebang (if any), before everything else."""
    if content.startswith("#!"):
        shebang, sep, rest = content.partition("\n")
        if sep:
            return f"{shebang}\n{LICENSE_HEADER}\n\n{rest}"
        # Shebang-only file with no newline — append a newline then header
        return f"{shebang}\n{LICENSE_HEADER}\n"
    return f"{LICENSE_HEADER}\n\n{content}"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    content = tool_input.get("content") or ""

    if not needs_header(file_path, content):
        return 0

    updated_input = dict(tool_input)
    updated_input["content"] = prepend_header(content)

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": updated_input,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
