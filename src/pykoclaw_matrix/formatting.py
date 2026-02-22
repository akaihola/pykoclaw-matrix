"""Markdown → Matrix HTML conversion.

Converts agent Markdown output into ``org.matrix.custom.html`` formatted
bodies for rich rendering in Element and other Matrix clients.

Uses ``markdown-it-py`` (CommonMark-compliant) instead of Python's ``markdown``
library for better handling of edge cases, plus strikethrough support.  Approach
borrowed from `akaihola/foam-web <https://github.com/akaihola/foam-web>`_.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

_md = MarkdownIt("commonmark", {"linkify": True}).enable(
    ["table", "strikethrough", "linkify"]
)
tasklists_plugin(_md)

# Patterns emitted by mdit-py-plugins tasklists — Element strips <input>
# elements, so we replace them with Unicode emoji checkboxes.
_CHECKED_RE = re.compile(
    r'<input class="task-list-item-checkbox"'
    r' checked="checked" disabled="disabled" type="checkbox">'
)
_UNCHECKED_RE = re.compile(
    r'<input class="task-list-item-checkbox"'
    r' disabled="disabled" type="checkbox">'
)

# Braille blank (U+2800) — renders as a visible space in Element on both
# desktop and mobile.  Two per nesting level.
_INDENT = "\u2800\u2800"


def _replace_checkboxes(html: str) -> str:
    """Replace ``<input>`` checkboxes with Unicode emoji symbols.

    Element (and most Matrix clients) sanitise HTML and strip ``<input>``
    elements entirely, leaving bare bullet points.  We substitute:

    - checked → ✅ (U+2705 WHITE HEAVY CHECK MARK)
    - unchecked → ⬛ (U+2B1B BLACK LARGE SQUARE)
    """
    html = _CHECKED_RE.sub("✅ ", html)
    html = _UNCHECKED_RE.sub("⬛ ", html)
    return html


# ---------------------------------------------------------------------------
# Pure task list flattening
# ---------------------------------------------------------------------------
#
# Element renders <ul> with bullet points that clash with our emoji checkboxes.
# For *pure* task lists (every <li> has class="task-list-item"), we flatten the
# <ul> into <br>-separated lines — no bullets.  Mixed lists (some <li> without
# the class) are left as standard <ul>.
#
# We parse the <ul class="contains-task-list"> blocks into a lightweight tree,
# check purity, and emit flattened output with Braille-blank indentation for
# nested items.


class _Node:
    """Minimal DOM node for task-list processing."""

    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []
        self.text = ""


# Void (self-closing) HTML elements that never get a </tag>.
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _TaskListParser(HTMLParser):
    """Parse a ``<ul class="contains-task-list">`` fragment into a tree."""

    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("root", {})
        self._stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(node)
        # Push all non-void elements so their children nest correctly.
        if tag not in _VOID_ELEMENTS:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        # Pop back to the matching open tag (skip past any unclosed inlines).
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        # Attach text to the current node.
        node = _Node("_text", {})
        node.text = data
        self._stack[-1].children.append(node)


def _is_pure_task_ul(node: _Node) -> bool:
    """Return True if *node* is a <ul> where every direct <li> is a task item.

    Nested <ul> children inside <li> are allowed — they are checked
    recursively.
    """
    if node.tag != "ul":
        return False
    li_children = [c for c in node.children if c.tag == "li"]
    if not li_children:
        return False
    for li in li_children:
        if "task-list-item" not in li.attrs.get("class", ""):
            return False
        # Check nested <ul> children recursively.
        for child in li.children:
            if child.tag == "ul" and not _is_pure_task_ul(child):
                return False
    return True


def _flatten_node(node: _Node, depth: int, lines: list[str]) -> None:
    """Recursively flatten a pure task-list <ul> into lines."""
    indent = _INDENT * depth
    for child in node.children:
        if child.tag != "li":
            continue
        # Collect inline content (text + inline HTML), skip nested <ul>.
        parts: list[str] = []
        nested_uls: list[_Node] = []
        for sub in child.children:
            if sub.tag == "ul":
                nested_uls.append(sub)
            elif sub.tag == "_text":
                parts.append(sub.text)
            else:
                # Reconstruct inline HTML (e.g. <strong>, <code>, <a>).
                parts.append(_reconstruct_html(sub))
        text = "".join(parts).strip()
        if text:
            lines.append(f"{indent}{text}")
        for nested in nested_uls:
            _flatten_node(nested, depth + 1, lines)


def _reconstruct_html(node: _Node) -> str:
    """Reconstruct an inline HTML node back to a string."""
    if node.tag == "_text":
        return node.text
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs.items())
    inner = "".join(_reconstruct_html(c) for c in node.children)
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


# Matches the opening tag of a task-list <ul>.
_TASK_UL_OPEN_RE = re.compile(r"<ul\s+class=\"contains-task-list\">")


def _find_matching_close(html: str, start: int) -> int | None:
    """Find the ``</ul>`` that closes the ``<ul>`` opened at *start*.

    Counts nested ``<ul>``/``</ul>`` pairs so inner lists don't fool us.
    Returns the index just past the closing ``</ul>``, or ``None``.
    """
    depth = 1
    pos = start
    while depth > 0:
        open_m = re.search(r"<ul[\s>]", html[pos:])
        close_m = re.search(r"</ul>", html[pos:])
        if close_m is None:
            return None
        close_abs = pos + close_m.start()
        if open_m is not None and pos + open_m.start() < close_abs:
            depth += 1
            pos = pos + open_m.start() + 3  # skip past "<ul"
        else:
            depth -= 1
            if depth == 0:
                return close_abs + len("</ul>")
            pos = close_abs + len("</ul>")
    return None


def _flatten_pure_task_lists(html: str) -> str:
    """Flatten pure task lists into ``<br>``-separated lines.

    Pure = every ``<li>`` has ``class="task-list-item"``.  Mixed lists are
    left unchanged as ``<ul>`` with bullets.
    """
    result: list[str] = []
    pos = 0
    while pos < len(html):
        m = _TASK_UL_OPEN_RE.search(html, pos)
        if m is None:
            result.append(html[pos:])
            break
        # Keep everything before this <ul>.
        result.append(html[pos : m.start()])
        # Find the matching </ul> (respecting nesting).
        inner_start = m.end()
        end = _find_matching_close(html, inner_start)
        if end is None:
            # Malformed — keep as-is.
            result.append(html[m.start() :])
            break
        full_block = html[m.start() : end]
        # Parse and check purity.
        parser = _TaskListParser()
        parser.feed(full_block)
        ul_nodes = [c for c in parser.root.children if c.tag == "ul"]
        if ul_nodes and _is_pure_task_ul(ul_nodes[0]):
            lines: list[str] = []
            _flatten_node(ul_nodes[0], depth=0, lines=lines)
            result.append("<br>\n".join(lines) + "\n")
        else:
            result.append(full_block)
        pos = end
    return "".join(result)


def markdown_to_matrix_html(text: str) -> str:
    """Convert Markdown text to Matrix-compatible HTML.

    Supports CommonMark (bold, italic, code, fenced code blocks, links, images,
    blockquotes, lists), plus GFM tables, ~~strikethrough~~, bare URL
    auto-linking, and ``- [x]`` / ``- [ ]`` task lists (rendered as Unicode
    emoji checkboxes on ``<br>``-separated lines for Matrix client
    compatibility).

    Returns the HTML string (may contain ``<p>``, ``<ul>``, ``<pre>``, etc.).
    """
    html = _md.render(text)
    html = _replace_checkboxes(html)
    html = _flatten_pure_task_lists(html)
    return html


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
