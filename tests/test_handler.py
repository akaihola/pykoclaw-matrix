"""Tests for Matrix message handler."""

from __future__ import annotations

import asyncio
import sqlite3
from textwrap import dedent
import pytest

from pykoclaw_matrix.handler import (
    BatchAccumulator,
    _is_hard_mention,
    format_xml_message,
    format_xml_messages,
    get_new_messages_for_room,
    store_message,
    update_agent_cursor,
    update_room_timestamp,
)


@pytest.fixture
def db() -> sqlite3.Connection:
    """Create in-memory database with Matrix tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript(
        dedent("""\
            CREATE TABLE matrix_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                sender TEXT,
                text TEXT,
                timestamp TEXT NOT NULL,
                is_from_me INTEGER DEFAULT 0
            );
            CREATE TABLE matrix_rooms (
                room_id TEXT PRIMARY KEY,
                name TEXT,
                last_timestamp TEXT,
                last_agent_timestamp TEXT
            );""")
    )
    return conn


def test_format_xml_message() -> None:
    """Test XML message formatting."""
    result = format_xml_message("Alice", "2024-01-01T12:00:00Z", "Hello world")
    assert '<message sender="Alice"' in result
    assert 'time="2024-01-01T12:00:00Z"' in result
    assert ">Hello world</message>" in result


def test_format_xml_message_escapes_html() -> None:
    """Test that XML formatting escapes HTML entities."""
    result = format_xml_message("Bob", "2024-01-01", "<script>alert('xss')</script>")
    assert "&lt;script&gt;" in result
    assert "&lt;/script&gt;" in result
    assert "<script>" not in result


def test_format_xml_messages() -> None:
    """Test formatting multiple messages as XML block."""
    messages = [
        ("Alice", "2024-01-01T12:00:00Z", "Hello"),
        ("Bob", "2024-01-01T12:01:00Z", "Hi there"),
    ]
    result = format_xml_messages(messages)

    assert result.startswith("<messages>")
    assert result.endswith("</messages>")
    assert "Alice" in result
    assert "Bob" in result
    assert "Hello" in result
    assert "Hi there" in result


def test_store_message(db: sqlite3.Connection) -> None:
    """Test storing a message in the database."""
    store_message(
        db,
        room_id="!abc123:matrix.org",
        sender="Alice",
        text="Test message",
        timestamp="2024-01-01T12:00:00Z",
        is_from_me=False,
    )

    rows = db.execute("SELECT * FROM matrix_messages").fetchall()
    assert len(rows) == 1
    assert rows[0]["room_id"] == "!abc123:matrix.org"
    assert rows[0]["sender"] == "Alice"
    assert rows[0]["text"] == "Test message"
    assert rows[0]["is_from_me"] == 0


def test_update_room_timestamp(db: sqlite3.Connection) -> None:
    """Test updating room timestamp."""
    update_room_timestamp(db, "!abc123:matrix.org", "2024-01-01T12:00:00Z")

    row = db.execute(
        "SELECT last_timestamp FROM matrix_rooms WHERE room_id = ?",
        ("!abc123:matrix.org",),
    ).fetchone()
    assert row["last_timestamp"] == "2024-01-01T12:00:00Z"


def test_update_agent_cursor(db: sqlite3.Connection) -> None:
    """Test updating per-room agent timestamp cursor."""
    update_agent_cursor(db, "!abc123:matrix.org", "2024-01-01T12:00:00Z")

    row = db.execute(
        "SELECT last_agent_timestamp FROM matrix_rooms WHERE room_id = ?",
        ("!abc123:matrix.org",),
    ).fetchone()
    assert row["last_agent_timestamp"] == "2024-01-01T12:00:00Z"


def test_get_new_messages_for_room(db: sqlite3.Connection) -> None:
    """Test retrieving new messages for a room."""
    store_message(
        db, "!abc123:matrix.org", "Alice", "Message 1", "2024-01-01T12:00:00Z", False
    )
    store_message(
        db, "!abc123:matrix.org", "Bob", "Message 2", "2024-01-01T12:01:00Z", False
    )
    store_message(
        db, "!abc123:matrix.org", "Alice", "Message 3", "2024-01-01T12:02:00Z", False
    )

    update_agent_cursor(db, "!abc123:matrix.org", "2024-01-01T12:00:30Z")

    messages = get_new_messages_for_room(db, "!abc123:matrix.org")

    assert len(messages) == 2
    assert messages[0][0] == "Bob"
    assert messages[0][2] == "Message 2"
    assert messages[1][0] == "Alice"
    assert messages[1][2] == "Message 3"


def test_get_new_messages_no_cursor(db: sqlite3.Connection) -> None:
    """Test retrieving messages when no agent cursor exists."""
    store_message(
        db, "!abc123:matrix.org", "Alice", "Message 1", "2024-01-01T12:00:00Z", False
    )
    store_message(
        db, "!abc123:matrix.org", "Bob", "Message 2", "2024-01-01T12:01:00Z", False
    )

    messages = get_new_messages_for_room(db, "!abc123:matrix.org")

    assert len(messages) == 2


def test_is_hard_mention() -> None:
    """Test hard mention detection."""
    assert _is_hard_mention("@Andy", "Andy")
    assert _is_hard_mention("hey @andy!", "Andy")
    assert _is_hard_mention("Andy what?", "Andy")
    assert _is_hard_mention("Andy, hi", "Andy")
    assert _is_hard_mention("andy: yo", "Andy")
    assert _is_hard_mention("Ok. Andy check this", "Andy")
    assert not _is_hard_mention("I told Andy about it", "Andy")
    assert not _is_hard_mention("Andyman is here", "Andy")


def test_is_hard_mention_multiple_names() -> None:
    """Verify cache handles different trigger names correctly."""
    assert _is_hard_mention("@Andy check this", "Andy")
    assert not _is_hard_mention("@Bob check this", "Andy")
    assert _is_hard_mention("@Bob check this", "Bob")
    assert not _is_hard_mention("@Andy check this", "Bob")


@pytest.mark.asyncio
async def test_batch_accumulator_timer() -> None:
    """Test that batch accumulator fires timer after window."""
    flushed: list[tuple[str, bool]] = []

    async def flush_cb(room_id: str, hard_mention: bool) -> None:
        flushed.append((room_id, hard_mention))

    acc = BatchAccumulator(window_seconds=0.05, flush_callback=flush_cb)
    await acc.add("!room1:test")

    await asyncio.sleep(0.1)
    assert len(flushed) == 1
    assert flushed[0] == ("!room1:test", False)


@pytest.mark.asyncio
async def test_batch_accumulator_flush_now() -> None:
    """Test immediate flush cancels pending timer."""
    flushed: list[tuple[str, bool]] = []

    async def flush_cb(room_id: str, hard_mention: bool) -> None:
        flushed.append((room_id, hard_mention))

    acc = BatchAccumulator(window_seconds=10.0, flush_callback=flush_cb)
    await acc.add("!room1:test")
    await acc.flush_now("!room1:test")

    assert len(flushed) == 1
    assert flushed[0] == ("!room1:test", True)


@pytest.mark.asyncio
async def test_batch_accumulator_no_double_fire() -> None:
    """Test that multiple adds don't reset the timer."""
    flushed: list[tuple[str, bool]] = []

    async def flush_cb(room_id: str, hard_mention: bool) -> None:
        flushed.append((room_id, hard_mention))

    acc = BatchAccumulator(window_seconds=0.05, flush_callback=flush_cb)
    await acc.add("!room1:test")
    await acc.add("!room1:test")  # Should NOT reset the timer
    await acc.add("!room1:test")

    await asyncio.sleep(0.1)
    assert len(flushed) == 1
