"""Tests for agent_harness.trace."""

import json
import tempfile
from pathlib import Path

from agent_harness.trace import Tracer


class TestTracer:
    def test_records_event_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(tmpdir)
            tracer.record("test_event", key="value")
            files = list(Path(tmpdir).glob("*.trace.jsonl"))
            assert len(files) == 1
            lines = files[0].read_text().strip().splitlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["event"] == "test_event"
            assert data["key"] == "value"
            assert "ts" in data

    def test_multiple_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(tmpdir)
            tracer.record("first")
            tracer.record("second", n=2)
            files = list(Path(tmpdir).glob("*.trace.jsonl"))
            lines = files[0].read_text().strip().splitlines()
            assert len(lines) == 2

    def test_valid_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(tmpdir)
            tracer.record("turn", turn=1, tokens=100)
            tracer.record("tool_call", tool="read_file")
            files = list(Path(tmpdir).glob("*.trace.jsonl"))
            for line in files[0].read_text().strip().splitlines():
                data = json.loads(line)  # should not raise
                assert "ts" in data
                assert "event" in data

    def test_no_log_dir_does_nothing(self) -> None:
        tracer = Tracer(None)
        tracer.record("should_not_crash", key="value")
        # No exception, no file created
