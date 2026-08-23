"""Integration tests: real concurrent writers never corrupt per-agent-dir state.

No mocks. Real threads, real filesystem. No API key needed — none of
save_memory/save_session/prepare_runtime touch a provider.
"""

import threading
from pathlib import Path

import yaml

from agent_harness.memory import recall_memory, save_memory
from agent_harness.permissions import PermissionDecision, Permissions
from agent_harness.session import Session, load_session, save_session
from agent_harness.types import Message, ToolCall

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
        file_path = str(tmp_path / "sessions" / "test.json")
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []

        def writer(idx: int) -> None:
            barrier.wait()
            for i in range(_ITERATIONS):
                msgs = [Message(role="user", content=f"writer-{idx}-iter-{i}")]
                session = Session(id="shared-session", name=None, messages=msgs)
                try:
                    save_session(session, file_path)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        loaded = load_session(file_path)
        # load_session's existing fail-safe returns None on corruption — a
        # non-empty, well-shaped result here is the actual proof there was
        # no garbled/half-written file for it to fall back on.
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content is not None and loaded.messages[0].content.startswith("writer-")


class TestConcurrentPermissionsWrites:
    def test_concurrent_saves_never_produce_corrupt_yaml(self, tmp_path: Path) -> None:
        persist_path = str(tmp_path / ".permissions.yaml")
        barrier = threading.Barrier(_N_THREADS)
        errors: list[BaseException] = []

        def writer(idx: int) -> None:
            barrier.wait()
            for i in range(_ITERATIONS):
                tool_name = f"writer-{idx}-iter-{i}"
                perms = Permissions(
                    {"always_ask": ["placeholder"]},
                    prompt_fn=lambda _tc: PermissionDecision.allow_persistent(),
                    persist_path=persist_path,
                )
                perms.check(ToolCall(id="tc", name=tool_name, arguments={}))
                try:
                    perms.save()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(_N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        data = yaml.safe_load(Path(persist_path).read_text())
        # A garbled/torn write would either fail to parse or produce a spliced
        # "approved" list mixing two writers' tool names — never observed here.
        possible = {f"writer-{w}-iter-{i}" for w in range(_N_THREADS) for i in range(_ITERATIONS)}
        assert data["approved"] == sorted({name for name in data["approved"] if name in possible})
        assert len(data["approved"]) == 1
