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

    def test_plain_text_no_formatting(self) -> None:
        html = markdown_to_matrix_html("Hello world")
        assert "Hello world" in html

    def test_multiline_paragraphs(self) -> None:
        md = "First paragraph.\n\nSecond paragraph."
        html = markdown_to_matrix_html(md)
        assert html.count("<p>") == 2


class TestTaskListCheckboxSymbols:
    """Checkbox symbols: ✅ for checked, ⬛ for unchecked."""

    def test_checked_symbol(self) -> None:
        html = markdown_to_matrix_html("- [x] Done task")
        assert "✅" in html
        assert "<input" not in html

    def test_unchecked_symbol(self) -> None:
        html = markdown_to_matrix_html("- [ ] Pending task")
        assert "⬛" in html
        assert "<input" not in html

    def test_mixed_symbols(self) -> None:
        md = "- [x] Done\n- [ ] Todo\n- [x] Also done"
        html = markdown_to_matrix_html(md)
        assert html.count("✅") == 2
        assert html.count("⬛") == 1


class TestPureTaskListFlattening:
    """Pure task lists (all items are tasks) → <br>-separated, no bullets."""

    def test_pure_task_list_no_bullets(self) -> None:
        md = "- [x] Done\n- [ ] Todo"
        html = markdown_to_matrix_html(md)
        assert "<ul" not in html
        assert "<li" not in html
        assert "<br>" in html
        assert "✅" in html
        assert "⬛" in html

    def test_pure_task_list_br_separated(self) -> None:
        md = "- [x] First\n- [ ] Second\n- [x] Third"
        html = markdown_to_matrix_html(md)
        lines = [line.strip() for line in html.split("<br>") if line.strip()]
        assert len(lines) == 3
        assert "First" in lines[0]
        assert "Second" in lines[1]
        assert "Third" in lines[2]

    def test_surrounding_content_preserved(self) -> None:
        md = "Text before\n\n- [x] Task\n- [ ] Another\n\nText after"
        html = markdown_to_matrix_html(md)
        assert "<p>Text before</p>" in html
        assert "<p>Text after</p>" in html
        assert "<ul" not in html
        assert "✅" in html

    def test_inline_formatting_preserved(self) -> None:
        md = "- [x] **Bold task**\n- [ ] `code task`\n- [x] [link](http://x.com)"
        html = markdown_to_matrix_html(md)
        assert "<strong>Bold task</strong>" in html
        assert "<code>code task</code>" in html
        assert '<a href="http://x.com">link</a>' in html
        assert "<ul" not in html

    def test_long_text_items(self) -> None:
        long = "A" * 200
        md = f"- [x] {long}\n- [ ] Short"
        html = markdown_to_matrix_html(md)
        assert long in html
        assert "<br>" in html
        assert "<ul" not in html


class TestMixedTaskList:
    """Mixed lists (tasks + plain items) → kept as <ul> with bullets."""

    def test_mixed_stays_as_ul(self) -> None:
        md = "- [x] Done\n- plain item\n- [ ] Todo"
        html = markdown_to_matrix_html(md)
        assert "<ul" in html
        assert "<li" in html

    def test_mixed_has_checkboxes(self) -> None:
        md = "- [x] Done\n- plain item\n- [ ] Todo"
        html = markdown_to_matrix_html(md)
        assert "✅" in html
        assert "⬛" in html

    def test_plain_list_unchanged(self) -> None:
        md = "- one\n- two\n- three"
        html = markdown_to_matrix_html(md)
        assert "<ul>" in html
        assert "<li>one</li>" in html


class TestNestedPureTaskList:
    """Nested pure task lists → indented with Braille blanks (U+2800)."""

    def test_nested_flattened(self) -> None:
        md = "- [x] Parent\n  - [ ] Child 1\n  - [x] Child 2\n- [ ] Another"
        html = markdown_to_matrix_html(md)
        assert "<ul" not in html
        assert "<li" not in html
        assert "<br>" in html

    def test_nested_indentation(self) -> None:
        md = "- [x] Parent\n  - [ ] Child"
        html = markdown_to_matrix_html(md)
        # Child line should start with Braille blanks (U+2800).
        braille = "\u2800\u2800"
        lines = [line for line in html.split("<br>") if line.strip()]
        child_lines = [line for line in lines if "Child" in line]
        assert len(child_lines) == 1
        assert braille in child_lines[0]

    def test_deeply_nested_indentation(self) -> None:
        md = "- [x] L1\n  - [x] L2\n    - [ ] L3"
        html = markdown_to_matrix_html(md)
        braille = "\u2800\u2800"
        lines = [line for line in html.split("<br>") if line.strip()]
        # L1: no indent, L2: 1 level, L3: 2 levels
        l1_lines = [x for x in lines if "L1" in x]
        l2_lines = [x for x in lines if "L2" in x]
        l3_lines = [x for x in lines if "L3" in x]
        assert not l1_lines[0].startswith(braille)
        assert l2_lines[0].lstrip("\n").startswith(braille)
        assert (braille * 2) in l3_lines[0]

    def test_nested_all_items_present(self) -> None:
        md = "- [x] Parent\n  - [ ] Child 1\n  - [x] Child 2\n- [ ] Sibling"
        html = markdown_to_matrix_html(md)
        for item in ["Parent", "Child 1", "Child 2", "Sibling"]:
            assert item in html, f"Missing item: {item}"


class TestEdgeCases:
    """Edge cases for task list formatting."""

    def test_empty_string(self) -> None:
        assert markdown_to_matrix_html("") == ""

    def test_single_task_item(self) -> None:
        html = markdown_to_matrix_html("- [x] Only one")
        assert "✅" in html
        assert "Only one" in html
        assert "<ul" not in html

    def test_task_list_between_other_content(self) -> None:
        md = "# Title\n\n- [x] Task\n\n> Quote"
        html = markdown_to_matrix_html(md)
        assert "<h1>" in html
        assert "✅" in html
        assert "<blockquote>" in html
        assert "<ul" not in html

    def test_multiple_task_lists(self) -> None:
        md = "- [x] List1 A\n- [ ] List1 B\n\nSeparator\n\n- [ ] List2 A\n- [x] List2 B"
        html = markdown_to_matrix_html(md)
        assert html.count("✅") == 2
        assert html.count("⬛") == 2
        assert "<ul" not in html


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
