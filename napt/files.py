# Copyright 2025 Roger Cibrian
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
# limitations under the License.

"""Filesystem helpers shared by every command that writes a record file.

Deployment state, promotion plan files, and the download sidecar are read
back by later runs and, in a GitOps setup, committed to git. They are
written through one helper that lands the file in a single rename, so a
write that fails part-way (a full disk, a killed process) leaves the
previous file in place rather than a truncated one.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Writes text to a file so the file is never seen part-written.

    The text goes to a temporary file in the same directory, which is
    then renamed over the target. Parent directories are created.

    Args:
        path: Destination file.
        text: Content to write.
        encoding: Text encoding.

    Raises:
        OSError: If the directory cannot be created, the temporary file
            cannot be written, or the rename fails. The target is left as
            it was, and the temporary file is removed.

    """
    write_bytes_atomic(path, text.encode(encoding))


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Writes bytes to a file so the file is never seen part-written.

    The bytes go to a temporary file in the same directory, which is then
    renamed over the target. Parent directories are created.

    Args:
        path: Destination file.
        data: Content to write.

    Raises:
        OSError: If the directory cannot be created, the temporary file
            cannot be written, or the rename fails. The target is left as
            it was, and the temporary file is removed.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
