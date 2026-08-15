"""Model-native binary content: building, extracting, and pruning attachments.

Two mechanisms live here:

- `build_attachment_from_file`: powers `view_image`/`view_document` —
  read a file the agent already has a path to, so it can become a real
  vision/document content block.
- `wrap_binary_output`/`extract_and_save_binary_output`: powers agent-
  produced binary output — a tool that creates fresh binary content (not
  already on disk) embeds it in its string output via a small envelope
  convention; the harness detects, decodes, guardrails, and saves it,
  replacing the envelope with a short text reference before it ever
  enters persisted history or the CLI display.

`prune_attachments` keeps only the most recently viewed attachment "live"
in what gets sent to the model, without mutating canonical history —
mirrors `loops/react.py::_with_budget_note`'s disposable-overlay pattern.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path

from agent_harness.types import Attachment, Message, ToolResult

_MAGIC_BYTES: dict[bytes, str] = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
    b"%PDF-": "application/pdf",
}

_MAX_ATTACHMENT_BYTES = 20_000_000

_ENVELOPE_MARKER = "<<<AGENT_HARNESS_FILE"
_ENVELOPE_PATTERN = re.compile(
    r'<<<AGENT_HARNESS_FILE filename="(?P<filename>[^"]*)" media_type="(?P<media_type>[^"]*)">>>\n'
    r"(?P<data>.*?)\n"
    r"<<<END_AGENT_HARNESS_FILE>>>",
    re.DOTALL,
)


def sniff_media_type(data: bytes) -> str | None:
    """Detect a media type from a file's leading bytes.

    Args:
        data: File content to inspect.

    Returns:
        The detected media type, or None if no known signature matches.
    """
    for signature, media_type in _MAGIC_BYTES.items():
        if data.startswith(signature):
            return media_type
    return None


def _kind_for_media_type(media_type: str) -> str:
    return "document" if media_type == "application/pdf" else "image"


def build_attachment_from_file(path: str, kind: str) -> Attachment:
    """Read a file and build an Attachment for it.

    Args:
        path: Path to the file.
        kind: Expected content kind — "image" or "document".

    Returns:
        The built Attachment, base64-encoded and ready to send to a provider.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is too large, its signature isn't
            recognized, or its actual kind doesn't match `kind`.
    """
    data = Path(path).read_bytes()
    if len(data) > _MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{path} is too large ({len(data)} bytes, max {_MAX_ATTACHMENT_BYTES})")
    media_type = sniff_media_type(data)
    if media_type is None:
        raise ValueError(f"Could not recognize {path}'s file signature")
    actual_kind = _kind_for_media_type(media_type)
    if actual_kind != kind:
        raise ValueError(f"{path} is a {actual_kind} ({media_type}), not a {kind}")
    return Attachment(kind=kind, media_type=media_type, data=base64.b64encode(data).decode(), filename=Path(path).name)


def wrap_binary_output(data: bytes, filename: str, media_type: str) -> str:
    """Build the binary-output envelope a tool embeds in its string output.

    Args:
        data: Raw file bytes.
        filename: Name to save the file as (must be a bare basename).
        media_type: The file's media type, e.g. "image/png".

    Returns:
        A string a tool can return as-is; the harness detects and
        extracts it in `execute_tool`.
    """
    encoded = base64.b64encode(data).decode()
    header = f'<<<AGENT_HARNESS_FILE filename="{filename}" media_type="{media_type}">>>'
    return f"{header}\n{encoded}\n<<<END_AGENT_HARNESS_FILE>>>"


def _validate_filename(filename: str) -> None:
    if not filename or filename in (".", "..") or Path(filename).name != filename:
        raise ValueError(f"Invalid filename: {filename!r}")


def extract_and_save_binary_output(output: str, tmp_dir: str) -> str:
    """Detect, decode, guardrail, and save an embedded binary-output envelope.

    A no-op (returns `output` unchanged) if no envelope is present — cheap,
    since this runs on every tool call.

    Args:
        output: Raw tool output, possibly containing a `wrap_binary_output`
            envelope.
        tmp_dir: Directory to save the decoded file into.

    Returns:
        `output` unchanged if no envelope was found, otherwise `output`
        with the envelope replaced by a short text reference.

    Raises:
        ValueError: If an envelope is present but malformed, its filename
            is unsafe, it exceeds the size cap, or its decoded content
            doesn't match its claimed media type.
    """
    if _ENVELOPE_MARKER not in output:
        return output
    match = _ENVELOPE_PATTERN.search(output)
    if match is None:
        raise ValueError("Malformed binary-output envelope")

    filename = match.group("filename")
    media_type = match.group("media_type")
    _validate_filename(filename)

    try:
        data = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Malformed base64 in binary-output envelope: {exc}") from exc

    if len(data) > _MAX_ATTACHMENT_BYTES:
        raise ValueError(f"Embedded file {filename} is too large ({len(data)} bytes, max {_MAX_ATTACHMENT_BYTES})")

    sniffed = sniff_media_type(data)
    if sniffed != media_type:
        raise ValueError(f"Embedded file {filename} claimed media_type={media_type!r} but signature says {sniffed!r}")

    target = Path(tmp_dir) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    reference = f"[saved: {filename} ({media_type}, {len(data) // 1024}KB) -> {target}]"
    return output[: match.start()] + reference + output[match.end() :]


def prune_attachments(messages: list[Message]) -> list[Message]:
    """Keep only the most recent attachment "live" for the next API call.

    Earlier attachment-bearing tool results are replaced with a short text
    reference in the returned overlay — the canonical `messages` list
    passed in is never mutated. Mirrors
    `loops/react.py::_with_budget_note`'s disposable-overlay pattern.

    Args:
        messages: Canonical conversation history.

    Returns:
        `messages` unchanged if at most one attachment is present,
        otherwise a new list with every attachment but the last stripped.
    """
    attachment_indices = [
        i for i, msg in enumerate(messages) if msg.tool_result is not None and msg.tool_result.attachment is not None
    ]
    if len(attachment_indices) <= 1:
        return messages

    overlay = list(messages)
    for i in attachment_indices[:-1]:
        tr = messages[i].tool_result
        assert tr is not None
        overlay[i] = Message(
            role=messages[i].role,
            content=messages[i].content,
            tool_result=ToolResult(tool_call_id=tr.tool_call_id, output=tr.output, error=tr.error),
        )
    return overlay
