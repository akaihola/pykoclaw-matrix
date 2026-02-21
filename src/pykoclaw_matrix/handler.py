"""Message event handler for Matrix rooms.

Handles incoming Matrix messages, stores them in the DB, and triggers the agent
via batch accumulation (same pattern as pykoclaw-whatsapp). Uses asyncio
natively since matrix-nio is async.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from html import escape as html_escape
from textwrap import dedent

from pykoclaw.db import DbConnection

log = logging.getLogger(__name__)

# Matches "@name" anywhere, or "name" followed by a separator (space, comma,
# colon, excl., question) at the start of the text or after a sentence-ending
# full stop.  All matching is case-insensitive.
_HARD_MENTION_CACHE: dict[str, re.Pattern[str]] = {}


def _build_hard_mention_re(trigger_name: str) -> re.Pattern[str]:
    name = re.escape(trigger_name)
    return re.compile(
        rf"@{name}\b"  # @Andy anywhere
        rf"|(?:^|(?<=\.\s))"  # start-of-string  OR  after ". "
        rf"{name}"  # the name itself
        rf"(?=[\s,:!?])",  # followed by separator
        re.IGNORECASE,
    )


def _is_hard_mention(text: str, trigger_name: str) -> bool:
    """Return *True* if *text* contains a hard mention of *trigger_name*."""
    if trigger_name not in _HARD_MENTION_CACHE:
        _HARD_MENTION_CACHE[trigger_name] = _build_hard_mention_re(trigger_name)
    return _HARD_MENTION_CACHE[trigger_name].search(text) is not None


class BatchAccumulator:
    """Per-room message batch accumulator with timer-based flushing.

    Accumulates messages in per-room batches. After the first message in a
    batch, a timer fires after ``window_seconds``. Hard mentions flush
    immediately via :meth:`flush_now`. A per-room :class:`asyncio.Lock`
    prevents concurrent agent calls for the same room.
    """

    def __init__(
        self,
        *,
        window_seconds: float,
        flush_callback: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        self._window = window_seconds
        self._flush_callback = flush_callback
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending_reflush: set[str] = set()

    def _get_lock(self, room_id: str) -> asyncio.Lock:
        if room_id not in self._locks:
            self._locks[room_id] = asyncio.Lock()
        return self._locks[room_id]

    async def add(self, room_id: str) -> None:
        """Schedule a batch timer for *room_id*.

        First message starts the timer. Subsequent messages within the window
        do NOT reset it (debounce, not throttle).  If the room is currently
        being flushed (lock held), the room is marked for re-flush.
        """
        lock = self._get_lock(room_id)
        if lock.locked():
            self._pending_reflush.add(room_id)
            return
        if room_id not in self._timers:
            loop = asyncio.get_running_loop()
            handle = loop.call_later(
                self._window,
                lambda rid=room_id: asyncio.ensure_future(self._timer_expired(rid)),
            )
            self._timers[room_id] = handle

    async def flush_now(self, room_id: str) -> None:
        """Immediately flush *room_id*'s batch (hard mention / DM)."""
        if room_id in self._timers:
            self._timers.pop(room_id).cancel()
        await self._do_flush(room_id, hard_mention=True)

    async def _timer_expired(self, room_id: str) -> None:
        self._timers.pop(room_id, None)
        await self._do_flush(room_id, hard_mention=False)

    async def _do_flush(self, room_id: str, *, hard_mention: bool) -> None:
        lock = self._get_lock(room_id)
        async with lock:
            await self._flush_callback(room_id, hard_mention)
        if room_id in self._pending_reflush:
            self._pending_reflush.discard(room_id)
            loop = asyncio.get_running_loop()
            handle = loop.call_later(
                self._window,
                lambda rid=room_id: asyncio.ensure_future(self._timer_expired(rid)),
            )
            self._timers[room_id] = handle


def format_xml_message(sender: str, timestamp: str, content: str) -> str:
    """Format a single message as XML."""
    return (
        f'<message sender="{html_escape(sender)}"'
        f' time="{html_escape(timestamp)}">'
        f"{html_escape(content)}</message>"
    )


def format_xml_messages(messages: list[tuple[str, str, str]]) -> str:
    """Format multiple messages as XML block for agent prompt."""
    lines = [format_xml_message(s, t, c) for s, t, c in messages]
    return f"<messages>\n{'\n'.join(lines)}\n</messages>"


def store_message(
    db: DbConnection,
    room_id: str,
    sender: str,
    text: str,
    timestamp: str,
    is_from_me: bool,
) -> None:
    """Store a Matrix message in the database."""
    db.execute(
        dedent("""\
            INSERT INTO matrix_messages (room_id, sender, text, timestamp, is_from_me)
            VALUES (?, ?, ?, ?, ?)"""),
        (room_id, sender, text, timestamp, 1 if is_from_me else 0),
    )
    db.commit()


def update_room_timestamp(db: DbConnection, room_id: str, timestamp: str) -> None:
    """Update a room's last message timestamp."""
    db.execute(
        dedent("""\
            INSERT INTO matrix_rooms (room_id, last_timestamp)
            VALUES (?, ?)
            ON CONFLICT(room_id) DO UPDATE SET
                last_timestamp = excluded.last_timestamp"""),
        (room_id, timestamp),
    )
    db.commit()


def update_agent_cursor(db: DbConnection, room_id: str, timestamp: str) -> None:
    """Update per-room agent timestamp cursor."""
    db.execute(
        dedent("""\
            INSERT INTO matrix_rooms (room_id, last_agent_timestamp)
            VALUES (?, ?)
            ON CONFLICT(room_id) DO UPDATE SET
                last_agent_timestamp = excluded.last_agent_timestamp"""),
        (room_id, timestamp),
    )
    db.commit()


def get_new_messages_for_room(
    db: DbConnection, room_id: str
) -> list[tuple[str, str, str]]:
    """Get messages newer than last agent timestamp for a room.

    Returns list of (sender, timestamp, text) tuples.
    """
    row = db.execute(
        "SELECT last_agent_timestamp FROM matrix_rooms WHERE room_id = ?", (room_id,)
    ).fetchone()
    since = row["last_agent_timestamp"] if row and row["last_agent_timestamp"] else ""

    rows = db.execute(
        dedent("""\
            SELECT sender, timestamp, text FROM matrix_messages
            WHERE room_id = ? AND timestamp > ?
            ORDER BY timestamp"""),
        (room_id, since),
    ).fetchall()
    return [(r["sender"], r["timestamp"], r["text"]) for r in rows]
