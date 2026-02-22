"""Mermaid diagram rendering for Matrix messages.

Detects ````` ```mermaid ````` code blocks in agent responses, renders them to
PNG via ``mermaid-cli`` (Playwright-based), and provides helpers to upload
them to the Matrix homeserver and send as ``m.image`` messages.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Matches fenced ```mermaid ... ``` blocks.  Captures the diagram source.
_MERMAID_BLOCK_RE = re.compile(
    r"```mermaid\s*\n(.*?)```",
    re.DOTALL,
)


def extract_mermaid_blocks(text: str) -> list[str]:
    """Return all Mermaid diagram sources from fenced code blocks in *text*."""
    return [m.group(1).strip() for m in _MERMAID_BLOCK_RE.finditer(text)]


def strip_mermaid_blocks(text: str) -> str:
    """Remove fenced Mermaid code blocks from *text*.

    The surrounding text is preserved; consecutive blank lines left by removal
    are collapsed to a single blank line.
    """
    result = _MERMAID_BLOCK_RE.sub("", text)
    # Collapse runs of 3+ newlines into 2 (one blank line).
    return re.sub(r"\n{3,}", "\n\n", result).strip()


async def render_mermaid_png(source: str) -> bytes | None:
    """Render a Mermaid diagram to PNG bytes.

    Uses ``mermaid-cli`` (Playwright + Chromium) with ``deviceScaleFactor=2``
    for sharp rendering.  Returns ``None`` on failure.
    """
    try:
        from mermaid_cli import render_mermaid

        _title, _desc, data = await render_mermaid(
            source,
            output_format="png",
            background_color="white",
            viewport={"width": 1600, "height": 1200, "deviceScaleFactor": 2},
        )
        log.info("Rendered Mermaid diagram: %d bytes", len(data))
        return data
    except Exception:
        log.exception("Failed to render Mermaid diagram")
        return None
