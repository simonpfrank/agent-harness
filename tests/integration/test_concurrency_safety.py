"""Integration tests: real concurrent writers never corrupt per-agent-dir state.

No mocks. Real threads, real filesystem. No API key needed — none of
save_memory/save_session/prepare_runtime touch a provider.
"""

import threading
import time
from pathlib import Path

import yaml

from agent_harness.loops.react import run as react_run
from agent_harness.memory import recall_memory, save_memory
from agent_harness.permissions import PermissionDecision, Permissions
from agent_harness.session import Session, load_session, save_session
from agent_harness.types import AgentConfig, Message, Response, ToolCall, Usage

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


def _config() -> AgentConfig:
    return AgentConfig(
        name="test", provider="anthropic", model="claude-haiku-4-5-20251001",
        agent_dir="/tmp/test", instructions="test",
    )


class TestParallelToolCallWallClockSpeedup:
    """Real, zero-mock proof that parallel tool-call execution actually
    overlaps at the OS level, not just at the Python-thread level: two real
    `run_command` calls (real subprocesses, each sleeping 1s) in one turn
    complete in ~1s total, not ~2s. No API key needed — chat_fn is a plain
    hand-written function, not a provider call."""

    def test_two_one_second_sleeps_complete_in_about_one_second(self) -> None:
        tc1 = ToolCall(id="tc_1", name="run_command", arguments={"command": "sleep 1"})
        tc2 = ToolCall(id="tc_2", name="run_command", arguments={"command": "sleep 1"})
        responses = iter([
            Response(
                message=Message(role="assistant", content="go", tool_calls=[tc1, tc2]),
                usage=Usage(10, 5), stop_reason="tool_use",
            ),
            Response(message=Message(role="assistant", content="done"), usage=Usage(10, 5), stop_reason="end_turn"),
        ])

        def chat_fn(*_args: object, **_kwargs: object) -> Response:
            return next(responses)

        messages = [Message(role="user", content="run two sleeps")]
        start = time.monotonic()
        react_run(chat_fn, messages, [], _config())
        elapsed = time.monotonic() - start

        assert elapsed < 1.7  # sequential would take >= 2.0s; parallel should land near 1.0s
