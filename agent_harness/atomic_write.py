"""Atomic text-file writes — same-directory temp file + rename."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def atomic_write_text(path: str | Path, content: str) -> None:
    """Write text to a file atomically.

    Writes to a uniquely-named temp file in the same directory as `path`
    (same filesystem, so the rename is atomic), then `os.replace`s it into
    place. A reader always sees either the complete old content or the
    complete new content — never a partial/interleaved write.

    Does not resolve *which* of two truly concurrent writers to the same
    path wins — the last `os.replace` wins (last-write-wins). Each writer
    uses its own uniquely-named temp file, so concurrent writers never
    collide on the temp file itself either.

    Args:
        path: Destination file path. Parent directory must already exist.
        content: Text to write.
    """
    target = Path(path)
    tmp_path = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, target)
