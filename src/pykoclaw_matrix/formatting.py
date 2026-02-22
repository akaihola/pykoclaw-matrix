"""Markdown → Matrix HTML conversion.

Converts agent Markdown output into ``org.matrix.custom.html`` formatted
bodies for rich rendering in Element and other Matrix clients.

Uses ``markdown-it-py`` (CommonMark-compliant) instead of Python's ``markdown``
library for better handling of edge cases, plus strikethrough support.  Approach
borrowed from `akaihola/foam-web <https://github.com/akaihola/foam-web>`_.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

_md = MarkdownIt("commonmark", {"linkify": True}).enable(
    ["table", "strikethrough", "linkify"]
)
tasklists_plugin(_md)

# Patterns emitted by mdit-py-plugins tasklists — Element strips <input>
# elements, so we replace them with Unicode checkbox symbols.
_CHECKED_RE = re.compile(
    r'<input class="task-list-item-checkbox"'
    r' checked="checked" disabled="disabled" type="checkbox">'
)
_UNCHECKED_RE = re.compile(
    r'<input class="task-list-item-checkbox"'
    r' disabled="disabled" type="checkbox">'
)


def _replace_checkboxes(html: str) -> str:
    """Replace ``<input>`` checkboxes with Unicode symbols.

    Element (and most Matrix clients) sanitise HTML and strip ``<input>``
    elements entirely, leaving bare bullet points.  We substitute:

    - checked → ☑ (U+2611 BALLOT BOX WITH CHECK)
    - unchecked → ☐ (U+2610 BALLOT BOX)
    """
    html = _CHECKED_RE.sub("☑ ", html)
    html = _UNCHECKED_RE.sub("☐ ", html)
    return html


def markdown_to_matrix_html(text: str) -> str:
    """Convert Markdown text to Matrix-compatible HTML.

    Supports CommonMark (bold, italic, code, fenced code blocks, links, images,
    blockquotes, lists), plus GFM tables, ~~strikethrough~~, bare URL
    auto-linking, and ``- [x]`` / ``- [ ]`` task lists (rendered as Unicode
    checkboxes for Matrix client compatibility).

    Returns the HTML string (may contain ``<p>``, ``<ul>``, ``<pre>``, etc.).
    """
    return _replace_checkboxes(_md.render(text))


def build_matrix_content(text: str) -> dict[str, str]:
    """Build the ``m.room.message`` content dict for *text*.

    Always includes a plain-text ``body`` (the original Markdown) **and** an
    HTML ``formatted_body`` so that clients that support rich formatting get
    nice rendering while older clients fall back to the plain text.
    """
    html = markdown_to_matrix_html(text)
    return {
        "msgtype": "m.text",
        "body": text,
        "format": "org.matrix.custom.html",
        "formatted_body": html,
    }
