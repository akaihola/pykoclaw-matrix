"""Tests for Matrix message formatting (Markdown → HTML)."""

from __future__ import annotations

from pykoclaw_matrix.formatting import build_matrix_content, markdown_to_matrix_html


class TestMarkdownToMatrixHtml:
    """Tests for markdown_to_matrix_html()."""

    def test_bold(self) -> None:
        assert "<strong>bold</strong>" in markdown_to_matrix_html("**bold**")

    def test_italic(self) -> None:
        assert "<em>italic</em>" in markdown_to_matrix_html("*italic*")

    def test_inline_code(self) -> None:
        assert "<code>foo</code>" in markdown_to_matrix_html("`foo`")

    def test_fenced_code_block(self) -> None:
        md = "```python\nprint(1)\n```"
        html = markdown_to_matrix_html(md)
        assert "<pre>" in html
        assert "<code" in html
        assert "print(1)" in html

    def test_link(self) -> None:
        html = markdown_to_matrix_html("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in html

    def test_unordered_list(self) -> None:
        md = "- one\n- two\n- three"
        html = markdown_to_matrix_html(md)
        assert "<ul>" in html
        assert "<li>one</li>" in html

    def test_ordered_list(self) -> None:
        md = "1. first\n2. second"
        html = markdown_to_matrix_html(md)
        assert "<ol>" in html
        assert "<li>first</li>" in html

    def test_table(self) -> None:
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = markdown_to_matrix_html(md)
        assert "<table>" in html
        assert "<th>" in html or "<td>" in html

    def test_strikethrough(self) -> None:
        assert "<s>deleted</s>" in markdown_to_matrix_html("~~deleted~~")

    def test_blockquote(self) -> None:
        html = markdown_to_matrix_html("> quoted text")
        assert "<blockquote>" in html
        assert "quoted text" in html

    def test_bare_url_linkified(self) -> None:
        html = markdown_to_matrix_html("Check https://example.com for details")
        assert '<a href="https://example.com">' in html

    def test_bare_url_does_not_double_link(self) -> None:
        """An explicit [text](url) link must not be double-wrapped."""
        html = markdown_to_matrix_html("[click](https://example.com)")
        assert html.count("<a ") == 1

    def test_task_list_checked(self) -> None:
        html = markdown_to_matrix_html("- [x] Done task")
        assert "☑" in html
        assert "<input" not in html

    def test_task_list_unchecked(self) -> None:
        html = markdown_to_matrix_html("- [ ] Pending task")
        assert "☐" in html
        assert "<input" not in html

    def test_task_list_mixed(self) -> None:
        md = "- [x] Done\n- [ ] Todo\n- [x] Also done"
        html = markdown_to_matrix_html(md)
        assert html.count("☑") == 2
        assert html.count("☐") == 1

    def test_plain_text_no_formatting(self) -> None:
        html = markdown_to_matrix_html("Hello world")
        assert "Hello world" in html

    def test_multiline_paragraphs(self) -> None:
        md = "First paragraph.\n\nSecond paragraph."
        html = markdown_to_matrix_html(md)
        assert html.count("<p>") == 2


class TestBuildMatrixContent:
    """Tests for build_matrix_content()."""

    def test_contains_required_keys(self) -> None:
        content = build_matrix_content("hello")
        assert content["msgtype"] == "m.text"
        assert content["format"] == "org.matrix.custom.html"
        assert "body" in content
        assert "formatted_body" in content

    def test_body_is_plain_text(self) -> None:
        md = "**bold** text"
        content = build_matrix_content(md)
        assert content["body"] == md  # Original Markdown preserved

    def test_formatted_body_is_html(self) -> None:
        content = build_matrix_content("**bold**")
        assert "<strong>bold</strong>" in content["formatted_body"]

    def test_complex_message(self) -> None:
        md = "Here is `code` and a [link](http://x.com)\n\n- item"
        content = build_matrix_content(md)
        html = content["formatted_body"]
        assert "<code>code</code>" in html
        assert '<a href="http://x.com">link</a>' in html
        assert "<li>item</li>" in html
