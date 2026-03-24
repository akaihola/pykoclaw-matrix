"""Tests for Matrix connection module."""

from __future__ import annotations

import io
import sqlite3
from textwrap import dedent
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nio import UploadResponse

from pykoclaw_matrix.connection import MatrixConnection, _extract_reply
from pykoclaw_matrix.handler import get_new_messages_for_room


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


# -- Integration: _handle_agent_trigger stores agent replies ----------------


@pytest.fixture
def matrix_db() -> sqlite3.Connection:
    """In-memory database with all required tables."""
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
            );
            CREATE TABLE conversations (
                name TEXT PRIMARY KEY,
                session_id TEXT,
                cwd TEXT,
                created_at TEXT NOT NULL
            );""")
    )
    return conn


@pytest.mark.asyncio
async def test_handle_agent_trigger_stores_reply(matrix_db: sqlite3.Connection) -> None:
    """After the agent replies, its response must be stored in matrix_messages
    with is_from_me=1 so it survives session resume failures."""
    from pykoclaw_messaging.dispatch import DispatchResult

    # Seed a user message
    matrix_db.execute(
        "INSERT INTO matrix_messages (room_id, sender, text, timestamp, is_from_me)"
        " VALUES (?, ?, ?, ?, ?)",
        ("!room:test", "Alice", "Hello Tyko", "2024-01-01T12:00:00Z", 0),
    )
    matrix_db.commit()

    fake_result = DispatchResult(
        full_text="thinking... <reply>Hi Alice!</reply>",
        session_id="sess-1",
    )

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._db = matrix_db
    conn._config = type("C", (), {"trigger_name": "Tyko"})()
    conn._extra_mcp_servers = {}
    conn._client = AsyncMock()
    conn._system_prompt_addition = None

    with (
        patch(
            "pykoclaw_matrix.connection.dispatch_to_agent",
            new_callable=AsyncMock,
            return_value=fake_result,
        ),
        patch("pykoclaw_matrix.connection.core_settings") as mock_settings,
    ):
        mock_settings.data = "/tmp/test"
        await conn._handle_agent_trigger("!room:test", hard_mention=True)

    # The agent reply must be stored locally
    rows = matrix_db.execute(
        "SELECT sender, text, is_from_me FROM matrix_messages ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 2
    agent_row = rows[1]
    assert agent_row["sender"] == "Tyko"
    assert agent_row["text"] == "Hi Alice!"
    assert agent_row["is_from_me"] == 1


@pytest.mark.asyncio
async def test_agent_reply_appears_in_next_batch(matrix_db: sqlite3.Connection) -> None:
    """Stored agent replies must appear in get_new_messages_for_room so the
    next XML context includes them — even after a session resume failure."""
    from pykoclaw_messaging.dispatch import DispatchResult

    # Seed a user message
    matrix_db.execute(
        "INSERT INTO matrix_messages (room_id, sender, text, timestamp, is_from_me)"
        " VALUES (?, ?, ?, ?, ?)",
        ("!room:test", "Alice", "Hello", "2024-01-01T12:00:00Z", 0),
    )
    matrix_db.commit()

    fake_result = DispatchResult(
        full_text="<reply>Hi!</reply>",
        session_id="sess-1",
    )

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._db = matrix_db
    conn._config = type("C", (), {"trigger_name": "Tyko"})()
    conn._extra_mcp_servers = {}
    conn._client = AsyncMock()
    conn._system_prompt_addition = None

    with (
        patch(
            "pykoclaw_matrix.connection.dispatch_to_agent",
            new_callable=AsyncMock,
            return_value=fake_result,
        ),
        patch("pykoclaw_matrix.connection.core_settings") as mock_settings,
    ):
        mock_settings.data = "/tmp/test"
        await conn._handle_agent_trigger("!room:test", hard_mention=True)

    # Now simulate a new user message arriving after the agent cursor was set
    matrix_db.execute(
        "INSERT INTO matrix_messages (room_id, sender, text, timestamp, is_from_me)"
        " VALUES (?, ?, ?, ?, ?)",
        ("!room:test", "Alice", "How are you?", "2024-01-01T12:02:00Z", 0),
    )
    matrix_db.commit()

    # The next batch should include the agent reply AND the new user message
    messages = get_new_messages_for_room(matrix_db, "!room:test")
    senders = [m[0] for m in messages]
    texts = [m[2] for m in messages]

    assert "Tyko" in senders, "Agent reply missing from next batch context"
    assert "Hi!" in texts
    assert "How are you?" in texts


# -- _send_image uploads with correct type ----------------------------------


@pytest.mark.asyncio
async def test_send_image_passes_bytesio_to_upload() -> None:
    """client.upload() requires a file-like object, not raw bytes."""
    fake_upload_resp = UploadResponse.from_dict(
        {"content_uri": "mxc://example.com/abc123"}
    )

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._client = AsyncMock()
    conn._client.upload = AsyncMock(return_value=(fake_upload_resp, None))
    conn._client.room_send = AsyncMock()

    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    await conn._send_image("!room:test", png_data, "diagram.png", "image/png")

    # Verify upload was called
    conn._client.upload.assert_called_once()
    call_args = conn._client.upload.call_args

    # The first positional arg must be a BytesIO, not raw bytes
    data_arg = call_args[0][0]
    assert isinstance(data_arg, io.BytesIO), (
        f"upload() received {type(data_arg).__name__}, expected BytesIO"
    )
    assert data_arg.read() == png_data

    # filesize must be passed
    assert call_args[1]["filesize"] == len(png_data)

    # room_send must have been called with m.image content
    conn._client.room_send.assert_called_once()
    send_args = conn._client.room_send.call_args
    assert send_args[0][1] == "m.room.message"
    content = send_args[0][2]
    assert content["msgtype"] == "m.image"
    assert content["url"] == "mxc://example.com/abc123"
    assert content["info"]["size"] == len(png_data)


@pytest.mark.asyncio
async def test_send_image_url_downloads_and_uploads() -> None:
    fake_upload_resp = UploadResponse.from_dict(
        {"content_uri": "mxc://example.com/urlimg"}
    )

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._client = AsyncMock()
    conn._client.upload = AsyncMock(return_value=(fake_upload_resp, None))
    conn._client.room_send = AsyncMock()

    response = Mock()
    response.content = b"PNGDATA"
    response.raise_for_status = Mock()

    async_client = AsyncMock()
    async_client.get = AsyncMock(return_value=response)
    async_client.__aenter__.return_value = async_client
    async_client.__aexit__.return_value = None

    with patch(
        "pykoclaw_matrix.connection.httpx.AsyncClient", return_value=async_client
    ):
        await conn._send_image_url("!room:test", "https://example.com/chart.png")

    conn._client.upload.assert_called_once()
    upload_args = conn._client.upload.call_args
    assert upload_args[1]["filename"] == "chart.png"
    assert upload_args[1]["content_type"] == "image/png"
    conn._client.room_send.assert_called_once()


# --- system_prompt_addition tests ---


def test_matrix_system_prompt_addition_appended(
    matrix_db: sqlite3.Connection,
) -> None:
    """system_prompt_addition is appended to the built system prompt."""
    from pykoclaw_matrix.config import MatrixSettings

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._config = MatrixSettings.model_construct(trigger_name="Tyko")
    conn._system_prompt_addition = "Always use full paths like `docs/note.md`."

    prompt = conn._build_system_prompt("!room:test", hard_mention=False)
    assert "Always use full paths like" in prompt


def test_matrix_system_prompt_addition_none_unchanged(
    matrix_db: sqlite3.Connection,
) -> None:
    """When system_prompt_addition is None, the prompt equals the base."""
    from pykoclaw_matrix.config import MatrixSettings

    conn_none = MatrixConnection.__new__(MatrixConnection)
    conn_none._config = MatrixSettings.model_construct(trigger_name="Tyko")
    conn_none._system_prompt_addition = None

    conn_base = MatrixConnection.__new__(MatrixConnection)
    conn_base._config = MatrixSettings.model_construct(trigger_name="Tyko")
    conn_base._system_prompt_addition = None

    room_id = "!room:test"
    assert conn_none._build_system_prompt(
        room_id, hard_mention=False
    ) == conn_base._build_system_prompt(room_id, hard_mention=False)


def test_matrix_system_prompt_addition_with_hard_mention(
    matrix_db: sqlite3.Connection,
) -> None:
    """system_prompt_addition is present even when hard_mention=True."""
    from pykoclaw_matrix.config import MatrixSettings

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._config = MatrixSettings.model_construct(trigger_name="Tyko")
    conn._system_prompt_addition = "Instruction from plugin."

    prompt = conn._build_system_prompt("!room:test", hard_mention=True)
    assert "Instruction from plugin." in prompt
    assert "MUST reply" in prompt  # hard-mention block is also present


# -- Delivery queue: response_transformer must be applied ------------------


@pytest.mark.asyncio
async def test_delivery_queue_applies_response_transformer(
    matrix_db: sqlite3.Connection,
) -> None:
    """response_transformer must be applied to queued delivery messages.

    Regression test: queued deliveries bypassed the transformer, so relative
    Markdown links like [label](relative/path.md) were sent as-is instead of
    being rewritten to Pykofinder URLs.
    """
    # Seed a delivery with a relative-path Markdown link
    matrix_db.execute(
        dedent("""\
            CREATE TABLE IF NOT EXISTS delivery_queue (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                task_run_log_id INTEGER,
                conversation TEXT NOT NULL,
                channel_prefix TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                delivered_at TEXT
            )""")
    )
    matrix_db.execute(
        dedent("""\
            INSERT INTO delivery_queue
                (id, task_id, conversation, channel_prefix, message, status, created_at)
            VALUES ('d1', 'task-1', 'matrix-!room:test', 'matrix',
                    'Report: [claw trends diary](journals/2026/claw-trends-diary.md)',
                    'pending', '2026-03-23T10:20:00+00:00')""")
    )
    matrix_db.commit()

    sent_texts: list[str] = []

    conn = MatrixConnection.__new__(MatrixConnection)
    conn._db = matrix_db
    conn._config = type("C", (), {"trigger_name": "Tyko"})()
    conn._extra_dbs: list = []
    conn._config.extra_db_paths = []
    conn._response_transformer = lambda text: text.replace(
        "[claw trends diary](journals/2026/claw-trends-diary.md)",
        "[claw trends diary](https://pykofinder.example.com/f/my-knowledge/journals/2026/claw-trends-diary.md)",
    )

    async def fake_send_message(room_id: str, text: str) -> None:
        sent_texts.append(text)

    conn._send_message = fake_send_message  # type: ignore[method-assign]

    await conn._process_deliveries_from_db(matrix_db)

    assert len(sent_texts) == 1, f"Expected 1 sent message, got {len(sent_texts)}"
    assert "https://pykofinder.example.com/f/my-knowledge/" in sent_texts[0], (
        f"Transformer not applied; sent: {sent_texts[0]!r}"
    )
    assert "journals/2026/claw-trends-diary.md" not in sent_texts[0].split(
        "https://pykofinder.example.com"
    )[0], "Raw relative path still present before the URL"
