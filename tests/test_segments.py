"""Tests for segment splitting logic."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from pykoclaw_matrix.segments import (
    ImageSegment,
    TextSegment,
    split_segments,
)


class TestSplitSegments:
    """Tests for split_segments()."""

    def test_plain_text_only(self) -> None:
        result = split_segments("Hello world")
        assert result == [TextSegment("Hello world")]

    def test_empty_string(self) -> None:
        result = split_segments("")
        assert result == []

    def test_whitespace_only(self) -> None:
        result = split_segments("   \n\n  ")
        assert result == []

    def test_single_mermaid_block(self) -> None:
        text = dedent("""\
            Here's a diagram:

            ```mermaid
            graph TD
              A-->B
            ```

            And some text after.""")
        result = split_segments(text)
        assert len(result) == 3
        assert isinstance(result[0], TextSegment)
        assert "Here's a diagram:" in result[0].text
        assert isinstance(result[1], ImageSegment)
        assert result[1].ref.kind == "mermaid"
        assert "graph TD" in result[1].ref.source
        assert isinstance(result[2], TextSegment)
        assert "text after" in result[2].text

    def test_mermaid_between_text(self) -> None:
        text = dedent("""\
            Before

            ```mermaid
            graph LR
              X-->Y
            ```

            After""")
        result = split_segments(text)
        assert len(result) == 3
        assert result[0] == TextSegment("Before")
        assert isinstance(result[1], ImageSegment)
        assert result[1].ref.kind == "mermaid"
        assert result[2] == TextSegment("After")

    def test_multiple_mermaid_blocks(self) -> None:
        text = dedent("""\
            First diagram:

            ```mermaid
            graph TD
              A-->B
            ```

            Second diagram:

            ```mermaid
            graph LR
              C-->D
            ```

            Done.""")
        result = split_segments(text)
        assert len(result) == 5
        assert isinstance(result[0], TextSegment)
        assert isinstance(result[1], ImageSegment)
        assert isinstance(result[2], TextSegment)
        assert isinstance(result[3], ImageSegment)
        assert isinstance(result[4], TextSegment)
        assert "A-->B" in result[1].ref.source
        assert "C-->D" in result[3].ref.source

    def test_image_file_path(self, tmp_path: Path) -> None:
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n")
        text = f"Here's the image: {img}\n\nSee above."
        result = split_segments(text)
        assert len(result) == 3
        assert isinstance(result[0], TextSegment)
        assert isinstance(result[1], ImageSegment)
        assert result[1].ref.kind == "file"
        assert result[1].ref.source == str(img)
        assert isinstance(result[2], TextSegment)

    def test_nonexistent_image_path_stays_as_text(self) -> None:
        text = "Look at /tmp/nonexistent-image-xyz.png for details."
        result = split_segments(text)
        assert len(result) == 1
        assert isinstance(result[0], TextSegment)

    def test_mixed_mermaid_and_file(self, tmp_path: Path) -> None:
        img = tmp_path / "chart.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        text = dedent(f"""\
            Here's a diagram:

            ```mermaid
            graph TD
              A-->B
            ```

            And here's a photo: {img}

            That's all.""")
        result = split_segments(text)
        assert len(result) == 5
        assert isinstance(result[0], TextSegment)
        assert isinstance(result[1], ImageSegment)
        assert result[1].ref.kind == "mermaid"
        assert isinstance(result[2], TextSegment)
        assert isinstance(result[3], ImageSegment)
        assert result[3].ref.kind == "file"
        assert isinstance(result[4], TextSegment)

    def test_only_mermaid_no_surrounding_text(self) -> None:
        text = dedent("""\
            ```mermaid
            graph TD
              A-->B
            ```""")
        result = split_segments(text)
        assert len(result) == 1
        assert isinstance(result[0], ImageSegment)
        assert result[0].ref.kind == "mermaid"

    def test_consecutive_mermaid_blocks_no_text_between(self) -> None:
        text = dedent("""\
            ```mermaid
            graph TD
              A-->B
            ```
            ```mermaid
            graph LR
              C-->D
            ```""")
        result = split_segments(text)
        assert len(result) == 2
        assert all(isinstance(s, ImageSegment) for s in result)

    def test_non_image_code_block_stays_as_text(self) -> None:
        text = dedent("""\
            ```python
            print("hello")
            ```""")
        result = split_segments(text)
        assert len(result) == 1
        assert isinstance(result[0], TextSegment)
        assert "python" in result[0].text

    def test_image_path_inside_mermaid_not_duplicated(self, tmp_path: Path) -> None:
        """An image path regex match inside a mermaid block should not produce
        a separate ImageSegment."""
        img = tmp_path / "note.png"
        img.write_bytes(b"\x89PNG")
        # The path appears inside the mermaid block — should only get mermaid
        text = dedent(f"""\
            ```mermaid
            graph TD
              A["{img}"]-->B
            ```""")
        result = split_segments(text)
        assert len(result) == 1
        assert isinstance(result[0], ImageSegment)
        assert result[0].ref.kind == "mermaid"

    def test_markdown_image_url(self) -> None:
        url = "https://example.com/plot.png"
        text = f"Before\n\n![plot]({url})\n\nAfter"
        result = split_segments(text)
        assert len(result) == 3
        assert isinstance(result[0], TextSegment)
        assert isinstance(result[1], ImageSegment)
        assert result[1].ref.kind == "url"
        assert result[1].ref.source == url
        assert isinstance(result[2], TextSegment)

    def test_markdown_image_url_inside_mermaid_not_duplicated(self) -> None:
        url = "https://example.com/plot.png"
        text = dedent(f"""\
            ```mermaid
            graph TD
              A["![plot]({url})"]-->B
            ```""")
        result = split_segments(text)
        assert len(result) == 1
        assert isinstance(result[0], ImageSegment)
        assert result[0].ref.kind == "mermaid"
