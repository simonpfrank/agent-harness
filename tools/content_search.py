"""Search file contents for a regex pattern (grep-equivalent)."""

import re
from pathlib import Path


def content_search(pattern: str, directory: str = ".") -> str:
    """Search file contents recursively for a regex pattern.

    Args:
        pattern: Regex pattern to search for.
        directory: Directory to search recursively.

    Returns:
        Newline-separated "path:line: text" matches, or a no-matches message.
    """
    base = Path(directory)
    if not base.is_dir():
        return "No matches found."
    regex = re.compile(pattern)
    matches: list[str] = []
    for file_path in sorted(base.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line_num, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{file_path}:{line_num}: {line}")
    return "\n".join(matches) if matches else "No matches found."
