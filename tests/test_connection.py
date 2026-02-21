"""Tests for Matrix connection module."""

from __future__ import annotations

from pykoclaw_matrix.connection import _extract_reply


def test_extract_reply_single() -> None:
    """Test extracting a single reply."""
    text = "Some reasoning. <reply>Hello world!</reply> More thinking."
    assert _extract_reply(text) == "Hello world!"


def test_extract_reply_multiple() -> None:
    """Test extracting multiple replies."""
    text = "<reply>First</reply> thinking <reply>Second</reply>"
    assert _extract_reply(text) == "First\nSecond"


def test_extract_reply_none() -> None:
    """Test returns None when no reply tags."""
    text = "Just some internal reasoning without any reply."
    assert _extract_reply(text) is None


def test_extract_reply_empty_tags() -> None:
    """Test returns None when reply tags are empty."""
    text = "<reply>   </reply>"
    assert _extract_reply(text) is None


def test_extract_reply_multiline() -> None:
    """Test extracting multiline reply content."""
    text = "<reply>Line one\nLine two\nLine three</reply>"
    assert _extract_reply(text) == "Line one\nLine two\nLine three"


def test_extract_reply_strips_whitespace() -> None:
    """Test that reply content is stripped."""
    text = "<reply>  Hello  </reply>"
    assert _extract_reply(text) == "Hello"
