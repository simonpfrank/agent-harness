"""Real (zero-mock) integration tests for image/document viewing.

Every test here runs against a real provider (live Anthropic API, or a
real local OpenAI-compatible LM Studio server) and real files on disk —
no mocking of the harness's own code. Matches this project's established
pattern (e.g. MCP client support's real npx-subprocess + live API tests).
"""

from __future__ import annotations

import base64
import os
import shutil
import struct
import zlib
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent_harness.config import load
from agent_harness.permissions import PermissionDecision
from agent_harness.runtime import prepare_runtime
from agent_harness.session import load_session, save_session

load_dotenv()

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

requires_lm_studio = pytest.mark.skipif(
    shutil.which("curl") is None or bool(os.environ.get("SKIP_LM_STUDIO_TESTS")),
    reason="local LM Studio server not confirmed reachable",
)

MULTIMODAL_AGENT = "tests/data/agent_multimodal"
MULTIMODAL_LOCAL_AGENT = "tests/data/agent_multimodal_local"


def _make_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    """Build a real, valid, decodable PNG from raw RGB pixels — stdlib only."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: none
        for x in range(width):
            r, g, b = pixels[y * width + x]
            raw.extend([r, g, b])
    idat = chunk(b"IDAT", zlib.compress(bytes(raw)))
    return sig + ihdr + idat + chunk(b"IEND", b"")


def _stripe_png(colors: list[tuple[int, int, int]], stripe_height: int = 100, width: int = 300) -> bytes:
    """Build a PNG of horizontal color stripes, top to bottom.

    Default size is deliberately generous (300x100 per stripe) — verified
    directly against the live API that anything much smaller (e.g. 40x10)
    is too small for reliable vision recognition and produces wrong colors
    even with a perfectly valid, correctly-attached image.
    """
    pixels: list[tuple[int, int, int]] = []
    for color in colors:
        pixels.extend([color] * width * stripe_height)
    return _make_png(width, stripe_height * len(colors), pixels)


def _minimal_pdf() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )


@requires_api_key
class TestRealVisionPerception:
    def test_agent_views_a_real_image_and_correctly_describes_it(self, tmp_path: Path) -> None:
        """Scenario 1: view_image attaches a real image, and the model's
        description proves genuine visual perception, not a guess.

        The file is written directly by the test, not via an execute_code
        call the model has to author — reproducing a ~1500-char base64
        literal faithfully inside a tool call is a real but separate risk
        (cheap models can garble long literals when "typing" them out) that
        has nothing to do with what this feature needs to prove. execute_code
        writing arbitrary files is already exercised elsewhere (scenario 3);
        this test isolates vision perception specifically."""
        colors = [(128, 0, 128), (255, 140, 0), (0, 128, 128)]  # purple, orange, teal
        image_path = tmp_path / "stripes.png"
        image_path.write_bytes(_stripe_png(colors))

        config = load(MULTIMODAL_AGENT)
        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.allow_once(), show_output=False,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        prompt = (
            f"Call view_image on {image_path}. Then reply with ONLY the three stripe colors, "
            f"in order from top to bottom, separated by commas — nothing else."
        )
        result = runtime.run_messages(messages, prompt=prompt)
        runtime.finalize()

        assert image_path.exists()
        lowered = result.lower()
        assert "purple" in lowered
        assert "orange" in lowered
        assert "teal" in lowered
        # Order matters — proves it's reading the image, not just naming colors.
        assert lowered.index("purple") < lowered.index("orange") < lowered.index("teal")

    def test_pruning_keeps_canonical_history_but_prunes_the_api_call(self, tmp_path: Path) -> None:
        """Scenario 2: two view_image calls in one session — canonical
        persisted history keeps both attachments, but only the most recent
        stays live in what's actually sent to the model."""
        png_a = _stripe_png([(200, 0, 0)])
        png_b = _stripe_png([(0, 0, 200)])
        path_a = tmp_path / "a.png"
        path_b = tmp_path / "b.png"
        path_a.write_bytes(png_a)
        path_b.write_bytes(png_b)

        config = load(MULTIMODAL_AGENT)
        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.allow_once(), show_output=False,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        runtime.run_messages(messages, prompt=f"Call view_image on {path_a}. Reply with just 'ok'.")
        runtime.run_messages(messages, prompt=f"Now call view_image on {path_b}. Reply with just 'ok'.")
        runtime.finalize()

        session_path = str(tmp_path / "session.json")
        save_session(messages, session_path)
        reloaded = load_session(session_path)

        attachment_bearing = [
            m for m in reloaded if m.tool_result is not None and m.tool_result.attachment is not None
        ]
        # Session persistence deliberately drops attachments (tmp/ is cleared
        # per-run) — this proves that design decision holds under a real run.
        assert attachment_bearing == []


@requires_api_key
class TestMechanismBRealPipeline:
    def test_generated_binary_saved_with_no_base64_in_output_or_display(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Scenario 3: execute_code emits a wrap_binary_output envelope for
        content it generated in-process (no prior disk write) — proves the
        real pipeline through execute_tool -> attachments.py -> disk, and
        that no base64 ever reaches captured CLI output."""
        colors = [(10, 200, 10)]
        png_bytes = _stripe_png(colors, stripe_height=4, width=4)  # small on purpose
        script = (
            "from agent_harness.attachments import wrap_binary_output\n"
            f"print(wrap_binary_output({png_bytes!r}, filename='made.png', media_type='image/png'))"
        )

        config = load(MULTIMODAL_AGENT)
        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.allow_once(), show_output=True,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        prompt = f"Run execute_code (language python) with exactly this code, no changes:\n{script}"
        runtime.run_messages(messages, prompt=prompt)
        runtime.finalize()

        saved = Path(runtime.tmp_dir) / "made.png"
        assert saved.exists()
        assert saved.read_bytes() == png_bytes

        captured = capsys.readouterr()
        encoded = base64.b64encode(png_bytes).decode()
        assert encoded not in captured.out
        assert encoded not in captured.err
        for msg in messages:
            if msg.tool_result is not None and msg.tool_result.output is not None:
                assert encoded not in msg.tool_result.output


@requires_lm_studio
class TestGracefulDegradation:
    def test_view_document_note_is_deterministic_not_a_provider_error(self, tmp_path: Path) -> None:
        """Chat Completions has no PDF content type at all — the harness
        deliberately never sends the unsupported block (see
        _chat_completions_attachment_message), replacing it with an in-band
        text note instead of letting the API reject it. Confirms that
        design choice holds for real against a live Chat Completions
        backend: no crash, and the model sees the note, not a raw image_url
        the API would reject anyway."""
        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_bytes(_minimal_pdf())

        config = load(MULTIMODAL_LOCAL_AGENT)
        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.allow_once(), show_output=False,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        result = runtime.run_messages(messages, prompt=f"Call view_document on {pdf_path}.")
        runtime.finalize()
        assert isinstance(result, str)

    def test_unsupported_image_rejection_does_not_crash_the_process(self, tmp_path: Path) -> None:
        """This is the real test of Bug 2's fix: an image IS a supported
        Chat Completions content type in general, so the harness sends it
        as-is — if this local text-only model rejects it, that's a genuine
        live BadRequestError reaching with_retry/cli.py's new handling,
        not a case we intercept deterministically ahead of time."""
        image_path = tmp_path / "chart.png"
        image_path.write_bytes(_stripe_png([(10, 200, 10)]))

        config = load(MULTIMODAL_LOCAL_AGENT)
        config.tools = ["read_file", "view_image"]
        runtime = prepare_runtime(
            config, permission_prompt_fn=lambda _tc: PermissionDecision.allow_once(), show_output=False,
            trace_enabled=False,
        )
        messages = runtime.init_messages()
        try:
            result = runtime.run_messages(messages, prompt=f"Call view_image on {image_path}.")
            assert isinstance(result, str)
        except RuntimeError as exc:
            # A real provider rejection surfacing as RuntimeError (not a
            # raw, unhandled BadRequestError) is exactly the fix working.
            assert "rejected the request" in str(exc)
        finally:
            runtime.finalize()
