"""Logging configuration for agent_harness."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(module)s %(funcName)s:%(lineno)d %(message)s"


def setup_logging(
    agent_dir: str | None = None,
    verbose: bool = False,
) -> None:
    """Configure console and optional file logging.

    Args:
        agent_dir: Agent directory for file logging. If None, file logging is skipped.
        verbose: If True, set console level to DEBUG. Default is INFO.
    """
    root = logging.getLogger("agent_harness")
    root.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates on repeated calls
    root.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console_handler)

    if agent_dir:
        log_dir = Path(agent_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        file_handler = logging.FileHandler(log_dir / f"{date_str}.log")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)
