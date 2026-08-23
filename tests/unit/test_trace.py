"""Tests for agent_harness.trace."""

import json
import tempfile
import threading
from pathlib import Path

from agent_harness.trace import Tracer

_N_THREADS = 20
_ITERATIONS = 25


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


class TestConcurrentRecording:
    """Parallel tool-call execution means genuinely concurrent record() calls
    from different threads within one run — previously impossible, since
    tool calls always ran one at a time."""

    def test_concurrent_records_never_corrupt_or_lose_a_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = Tracer(tmpdir)
            barrier = threading.Barrier(_N_THREADS)
            errors: list[BaseException] = []

            def writer(idx: int) -> None:
                barrier.wait()  # maximize actual overlap, not staggered starts
                for i in range(_ITERATIONS):
                    try:
                        tracer.record("tool_call", writer=idx, iteration=i)
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(_N_THREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == []
            files = list(Path(tmpdir).glob("*.trace.jsonl"))
            lines = files[0].read_text().strip().splitlines()
            # Every line parses (no torn/interleaved write) and none were lost.
            parsed = [json.loads(line) for line in lines]
            assert len(parsed) == _N_THREADS * _ITERATIONS
            seen = {(entry["writer"], entry["iteration"]) for entry in parsed}
            assert seen == {(w, i) for w in range(_N_THREADS) for i in range(_ITERATIONS)}
