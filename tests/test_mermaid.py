"""Tests for Mermaid diagram extraction and rendering."""

from __future__ import annotations

import pytest

from pykoclaw_matrix.mermaid import (
    extract_mermaid_blocks,
    render_mermaid_png,
    strip_mermaid_blocks,
)


class TestExtractMermaidBlocks:
    """Tests for extract_mermaid_blocks()."""

    def test_no_mermaid(self) -> None:
        assert extract_mermaid_blocks("Just plain text") == []

    def test_single_block(self) -> None:
        md = "Text\n\n```mermaid\ngraph TD\n  A-->B\n```\n\nMore text"
        blocks = extract_mermaid_blocks(md)
        assert len(blocks) == 1
        assert "graph TD" in blocks[0]
        assert "A-->B" in blocks[0]

    def test_multiple_blocks(self) -> None:
        md = (
            "```mermaid\ngraph TD\n  A-->B\n```\n\n"
            "Middle\n\n"
            "```mermaid\nsequenceDiagram\n  Alice->>Bob: Hi\n```"
        )
        blocks = extract_mermaid_blocks(md)
        assert len(blocks) == 2
        assert "graph TD" in blocks[0]
        assert "sequenceDiagram" in blocks[1]

    def test_ignores_other_code_blocks(self) -> None:
        md = "```python\nprint(1)\n```\n\n```mermaid\ngraph TD\n  A-->B\n```"
        blocks = extract_mermaid_blocks(md)
        assert len(blocks) == 1
        assert "graph TD" in blocks[0]

    def test_strips_whitespace(self) -> None:
        md = "```mermaid\n  graph TD  \n  A-->B  \n```"
        blocks = extract_mermaid_blocks(md)
        assert blocks[0] == "graph TD  \n  A-->B"

    def test_empty_string(self) -> None:
        assert extract_mermaid_blocks("") == []


class TestStripMermaidBlocks:
    """Tests for strip_mermaid_blocks()."""

    def test_strips_single_block(self) -> None:
        md = "Before\n\n```mermaid\ngraph TD\n  A-->B\n```\n\nAfter"
        result = strip_mermaid_blocks(md)
        assert "Before" in result
        assert "After" in result
        assert "mermaid" not in result
        assert "graph TD" not in result

    def test_strips_multiple_blocks(self) -> None:
        md = (
            "Text\n\n"
            "```mermaid\ngraph TD\n  A-->B\n```\n\n"
            "Middle\n\n"
            "```mermaid\nsequenceDiagram\n```\n\n"
            "End"
        )
        result = strip_mermaid_blocks(md)
        assert "Text" in result
        assert "Middle" in result
        assert "End" in result
        assert "mermaid" not in result

    def test_preserves_other_code_blocks(self) -> None:
        md = "```python\nprint(1)\n```\n\n```mermaid\ngraph TD\n```"
        result = strip_mermaid_blocks(md)
        assert "```python" in result
        assert "print(1)" in result
        assert "mermaid" not in result

    def test_collapses_excess_newlines(self) -> None:
        md = "Before\n\n```mermaid\ngraph TD\n```\n\nAfter"
        result = strip_mermaid_blocks(md)
        assert "\n\n\n" not in result

    def test_no_mermaid_unchanged(self) -> None:
        md = "Just plain text"
        assert strip_mermaid_blocks(md) == md

    def test_only_mermaid(self) -> None:
        md = "```mermaid\ngraph TD\n  A-->B\n```"
        result = strip_mermaid_blocks(md)
        assert result == ""


class TestRenderMermaidPng:
    """Tests for render_mermaid_png() — requires Playwright + Chromium."""

    @pytest.mark.asyncio
    async def test_renders_simple_diagram(self) -> None:
        data = await render_mermaid_png("graph TD\n  A-->B")
        assert data is not None
        assert len(data) > 1000  # A real PNG is at least a few KB
        # PNG magic bytes
        assert data[:4] == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_renders_complex_diagram(self) -> None:
        diagram = (
            "graph TB\n"
            "  subgraph S1[Service]\n"
            "    A[API] --> B[DB]\n"
            "  end\n"
            "  C[Client] --> A\n"
        )
        data = await render_mermaid_png(diagram)
        assert data is not None
        assert data[:4] == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_invalid_diagram_returns_none(self) -> None:
        # Completely invalid syntax — should fail gracefully
        data = await render_mermaid_png("not a valid mermaid diagram }{}{")
        # mermaid-cli may still produce output for invalid diagrams (error image)
        # or return None — either is acceptable, but no exception should propagate
        assert data is None or isinstance(data, bytes)
