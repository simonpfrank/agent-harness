"""Tests for agent_harness.attachments."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from agent_harness import attachments
from agent_harness.attachments import (
    build_attachment_from_file,
    extract_and_save_binary_output,
    prune_attachments,
    sniff_media_type,
    wrap_binary_output,
)
from agent_harness.types import Message, ToolResult

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32
_GIF_BYTES = b"GIF89a" + b"\x00" * 32
_PDF_BYTES = b"%PDF-1.7\n" + b"\x00" * 32
_JUNK_BYTES = b"not a real file" * 4


class TestSniffMediaType:
    def test_png(self) -> None:
        assert sniff_media_type(_PNG_BYTES) == "image/png"

    def test_jpeg(self) -> None:
        assert sniff_media_type(_JPEG_BYTES) == "image/jpeg"

    def test_gif(self) -> None:
        assert sniff_media_type(_GIF_BYTES) == "image/gif"

    def test_pdf(self) -> None:
        assert sniff_media_type(_PDF_BYTES) == "application/pdf"

    def test_unrecognized_returns_none(self) -> None:
        assert sniff_media_type(_JUNK_BYTES) is None


class TestBuildAttachmentFromFile:
    def test_image_success(self, tmp_path: Path) -> None:
        path = tmp_path / "chart.png"
        path.write_bytes(_PNG_BYTES)
        attachment = build_attachment_from_file(str(path), kind="image")
        assert attachment.kind == "image"
        assert attachment.media_type == "image/png"
        assert attachment.filename == "chart.png"
        assert base64.b64decode(attachment.data) == _PNG_BYTES

    def test_document_success(self, tmp_path: Path) -> None:
        path = tmp_path / "report.pdf"
        path.write_bytes(_PDF_BYTES)
        attachment = build_attachment_from_file(str(path), kind="document")
        assert attachment.kind == "document"
        assert attachment.media_type == "application/pdf"

    def test_kind_mismatch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "report.pdf"
        path.write_bytes(_PDF_BYTES)
        with pytest.raises(ValueError, match="kind"):
            build_attachment_from_file(str(path), kind="image")

    def test_unrecognized_signature_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "mystery.bin"
        path.write_bytes(_JUNK_BYTES)
        with pytest.raises(ValueError, match="signature|recognize"):
            build_attachment_from_file(str(path), kind="image")

    def test_oversize_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attachments, "_MAX_ATTACHMENT_BYTES", 8)
        path = tmp_path / "chart.png"
        path.write_bytes(_PNG_BYTES)
        with pytest.raises(ValueError, match="size|large"):
            build_attachment_from_file(str(path), kind="image")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            build_attachment_from_file(str(tmp_path / "nope.png"), kind="image")


class TestExtractAndSaveBinaryOutput:
    def test_no_envelope_passthrough_is_a_noop(self, tmp_path: Path) -> None:
        plain = "just some ordinary tool output"
        assert extract_and_save_binary_output(plain, str(tmp_path)) == plain

    def test_well_formed_envelope_saves_and_replaces(self, tmp_path: Path) -> None:
        envelope = wrap_binary_output(_PNG_BYTES, filename="chart.png", media_type="image/png")
        result = extract_and_save_binary_output(envelope, str(tmp_path))
        saved = tmp_path / "chart.png"
        assert saved.read_bytes() == _PNG_BYTES
        assert "chart.png" in result
        assert base64.b64encode(_PNG_BYTES).decode() not in result

    def test_malformed_base64_raises(self, tmp_path: Path) -> None:
        bad = (
            '<<<AGENT_HARNESS_FILE filename="x.png" media_type="image/png">>>\n'
            "not-valid-base64!!!\n"
            "<<<END_AGENT_HARNESS_FILE>>>"
        )
        with pytest.raises(ValueError):
            extract_and_save_binary_output(bad, str(tmp_path))

    def test_path_traversal_filename_rejected(self, tmp_path: Path) -> None:
        envelope = wrap_binary_output(_PNG_BYTES, filename="../../etc/evil.png", media_type="image/png")
        with pytest.raises(ValueError, match="filename"):
            extract_and_save_binary_output(envelope, str(tmp_path))

    def test_absolute_filename_rejected(self, tmp_path: Path) -> None:
        envelope = wrap_binary_output(_PNG_BYTES, filename="/etc/evil.png", media_type="image/png")
        with pytest.raises(ValueError, match="filename"):
            extract_and_save_binary_output(envelope, str(tmp_path))

    def test_oversize_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(attachments, "_MAX_ATTACHMENT_BYTES", 8)
        envelope = wrap_binary_output(_PNG_BYTES, filename="chart.png", media_type="image/png")
        with pytest.raises(ValueError, match="size|large"):
            extract_and_save_binary_output(envelope, str(tmp_path))

    def test_signature_mismatch_raises(self, tmp_path: Path) -> None:
        # Claims to be a PNG but the decoded bytes are junk.
        envelope = wrap_binary_output(_JUNK_BYTES, filename="chart.png", media_type="image/png")
        with pytest.raises(ValueError, match="signature|match"):
            extract_and_save_binary_output(envelope, str(tmp_path))


class TestPruneAttachments:
    def _msg_with_attachment(self, filename: str) -> Message:
        from agent_harness.types import Attachment

        return Message(
            role="tool",
            tool_result=ToolResult(
                tool_call_id="tc",
                output=f"Viewing {filename}",
                attachment=Attachment(kind="image", media_type="image/png", data="abc", filename=filename),
            ),
        )

    def test_no_attachments_returns_same_list(self) -> None:
        messages = [Message(role="user", content="hi")]
        assert prune_attachments(messages) is messages

    def test_single_attachment_returns_same_list(self) -> None:
        messages = [Message(role="user", content="hi"), self._msg_with_attachment("a.png")]
        assert prune_attachments(messages) is messages

    def test_only_last_attachment_stays_live(self) -> None:
        first = self._msg_with_attachment("a.png")
        second = self._msg_with_attachment("b.png")
        messages = [Message(role="user", content="hi"), first, second]

        pruned = prune_attachments(messages)

        assert pruned[1].tool_result is not None
        assert pruned[1].tool_result.attachment is None
        assert "a.png" in (pruned[1].tool_result.output or "")
        assert pruned[2].tool_result is not None
        assert pruned[2].tool_result.attachment is not None

    def test_canonical_list_never_mutated(self) -> None:
        first = self._msg_with_attachment("a.png")
        second = self._msg_with_attachment("b.png")
        messages = [Message(role="user", content="hi"), first, second]

        prune_attachments(messages)

        assert messages[1] is first
        assert first.tool_result is not None
        assert first.tool_result.attachment is not None
