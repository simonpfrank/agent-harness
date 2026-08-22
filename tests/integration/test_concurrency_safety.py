"""Integration tests: real concurrent writers never corrupt per-agent-dir state.

No mocks. Real threads, real filesystem. No API key needed — none of
save_memory/save_session/prepare_runtime touch a provider.
"""

import threading
from pathlib import Path

from agent_harness.memory import recall_memory, save_memory
from agent_harness.session import load_session, save_session
from agent_harness.types import Message

_N_THREADS = 20
_ITERATIONS = 25


class TestConcurrentMemoryWrites:
    def test_concurrent_saves_never_produce_garbled_file(self, tmp_path: Path) -> None:
        memory_dir = str(tmp_path / "memory")
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []

        def writer(idx: int) -> None:
            barrier.wait()  # maximize actual overlap, not staggered starts
            for i in range(_ITERATIONS):
                try:
                    save_memory("shared-key", f"writer-{idx}-iter-{i}", memory_dir)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        final = recall_memory("shared-key", memory_dir)
        possible = {f"writer-{w}-iter-{i}" for w in range(_N_THREADS) for i in range(_ITERATIONS)}
        assert final in possible  # exactly one complete write, never a splice of two


class TestConcurrentSessionWrites:
    def test_concurrent_saves_never_produce_corrupt_json(self, tmp_path: Path) -> None:
        session_path = str(tmp_path / "sessions" / "test.json")
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []

        def writer(idx: int) -> None:
            barrier.wait()
            for i in range(_ITERATIONS):
                msgs = [Message(role="user", content=f"writer-{idx}-iter-{i}")]
                try:
                    save_session(msgs, session_path)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        loaded = load_session(session_path)
        # load_session's existing fail-safe returns [] on corruption — a
        # non-empty, well-shaped result here is the actual proof there was
        # no garbled/half-written file for it to fall back on.
        assert len(loaded) == 1
        assert loaded[0].content is not None and loaded[0].content.startswith("writer-")
