"""Tests for agent_harness.atomic_write."""

import threading
from pathlib import Path

from agent_harness.atomic_write import atomic_write_text


class TestAtomicWriteText:
    def test_writes_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "note.md"
        atomic_write_text(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "note.md"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_no_stray_temp_file_left_behind(self, tmp_path: Path) -> None:
        target = tmp_path / "note.md"
        atomic_write_text(target, "hello")
        entries = list(tmp_path.iterdir())
        assert entries == [target]

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        target = tmp_path / "note.md"
        atomic_write_text(str(target), "hello")
        assert target.read_text() == "hello"

    def test_concurrent_writers_never_corrupt_the_file(self, tmp_path: Path) -> None:
        target = tmp_path / "shared.md"
        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []

        def writer(idx: int) -> None:
            barrier.wait()
            for i in range(25):
                try:
                    atomic_write_text(target, f"writer-{idx}-iter-{i}")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        final = target.read_text()
        possible = {f"writer-{w}-iter-{i}" for w in range(n_threads) for i in range(25)}
        assert final in possible
