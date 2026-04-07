"""Search for files matching a glob pattern."""

from pathlib import Path


def file_search(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern in a directory.

    Args:
        pattern: Glob pattern (e.g. "*.py", "**/*.md").
        directory: Directory to search in.

    Returns:
        Newline-separated list of matching file paths.
    """
    matches = sorted(str(p) for p in Path(directory).glob(pattern))
    return "\n".join(matches) if matches else "No files found."
