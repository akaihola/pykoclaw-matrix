"""Split agent text into interleaved text and image segments.

Walks the text linearly, identifying Mermaid code blocks, image file paths,
and Markdown image URLs in document order, and yields ``TextSegment`` or
``ImageSegment`` objects so the caller can send them as separate Matrix
messages in the correct order.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .images import IMAGE_EXTENSIONS, IMAGE_PATH_RE, IMAGE_URL_MD_RE
from .mermaid import MERMAID_BLOCK_RE

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImageRef:
    """A reference to an image that should be sent as ``m.image``."""

    kind: Literal["mermaid", "file", "url"]
    """Whether this came from a Mermaid block, a file path, or a remote URL."""

    source: str
    """Mermaid diagram source text, the absolute file path, or the remote URL."""


@dataclass(frozen=True, slots=True)
class TextSegment:
    """A plain-text segment to send as a formatted message."""

    text: str


@dataclass(frozen=True, slots=True)
class ImageSegment:
    """An image segment to render/read/download and send as ``m.image``."""

    ref: ImageRef


Segment = TextSegment | ImageSegment


def split_segments(text: str) -> list[Segment]:
    """Split *text* into an ordered list of text and image segments.

    Mermaid code blocks, image file paths, and Markdown HTTP image URLs are
    detected in document order. Text between them becomes ``TextSegment``
    entries. Empty text segments (only whitespace) are dropped.
    """
    markers: list[tuple[int, int, ImageRef]] = []

    for m in MERMAID_BLOCK_RE.finditer(text):
        markers.append((m.start(), m.end(), ImageRef("mermaid", m.group(1).strip())))

    for m in IMAGE_URL_MD_RE.finditer(text):
        markers.append((m.start(), m.end(), ImageRef("url", m.group(2))))

    for m in IMAGE_PATH_RE.finditer(text):
        raw = m.group(1)
        p = Path(raw)
        if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file():
            markers.append((m.start(), m.end(), ImageRef("file", raw)))

    markers.sort(key=lambda t: t[0])

    filtered: list[tuple[int, int, ImageRef]] = []
    last_end = 0
    for start, end, ref in markers:
        if start >= last_end:
            filtered.append((start, end, ref))
            last_end = end

    segments: list[Segment] = []
    pos = 0
    for start, end, ref in filtered:
        chunk = text[pos:start]
        _maybe_add_text(segments, chunk)
        segments.append(ImageSegment(ref))
        pos = end

    _maybe_add_text(segments, text[pos:])
    return segments


def _maybe_add_text(segments: list[Segment], chunk: str) -> None:
    """Append a ``TextSegment`` if *chunk* has non-whitespace content."""
    cleaned = re.sub(r"\n{3,}", "\n\n", chunk).strip()
    if cleaned:
        segments.append(TextSegment(cleaned))
