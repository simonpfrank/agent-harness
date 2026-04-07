"""Structured trace file — newline-delimited JSON events per run."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Tracer:
    """Records timestamped events to a JSONL trace file.

    Inert if no log_dir is provided.

    Args:
        log_dir: Directory for trace files. None disables tracing.
    """

    def __init__(self, log_dir: str | None) -> None:
        self._file: Path | None = None
        if log_dir:
            path = Path(log_dir)
            path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H-%M-%S")
            self._file = path / f"{timestamp}.trace.jsonl"

    def record(self, event: str, **data: Any) -> None:
        """Record a timestamped event.

        Args:
            event: Event type (e.g. "turn", "tool_call", "budget").
            **data: Arbitrary event data.
        """
        if self._file is None:
            return
        entry = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "event": event,
            **data,
        }
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logging.getLogger(__name__).warning("Trace write failed: %s", exc)
