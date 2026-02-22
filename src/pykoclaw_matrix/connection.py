"""Matrix connection lifecycle manager.

Manages the matrix-nio AsyncClient, event registration, sync loop, and the
agent trigger pipeline. Modeled after pykoclaw-whatsapp's WhatsAppConnection.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from textwrap import dedent
from typing import Any

from nio import (
    AsyncClient,
    ClientConfig,
    InviteMemberEvent,
    LoginError,
    MatrixRoom,
    MegolmEvent,
    RoomMessageText,
)

from pykoclaw.config import settings as core_settings
from pykoclaw.db import (
    DbConnection,
    get_pending_deliveries,
    mark_delivered,
    mark_delivery_failed,
)
from pykoclaw_messaging import dispatch_to_agent

from .config import MatrixSettings, get_config
from .formatting import build_matrix_content
from .handler import (
    BatchAccumulator,
    _is_hard_mention,
    format_xml_messages,
    get_new_messages_for_room,
    store_message,
    update_agent_cursor,
    update_room_timestamp,
)

log = logging.getLogger(__name__)


def _extract_reply(text: str) -> str | None:
    """Extract text wrapped in <reply> tags from agent output.

    Uses allowlist-based filtering: only text explicitly wrapped in <reply> tags
    is returned. All other text (internal monologue, reasoning) is discarded.

    Args:
        text: Raw agent output potentially containing <reply> tags.

    Returns:
        Joined non-empty reply content, or None if no valid replies found.
    """
    matches = re.findall(r"<reply>(.*?)</reply>", text, re.DOTALL)
    stripped = [m.strip() for m in matches]
    filtered = [m for m in stripped if m]
    return "\n".join(filtered) if filtered else None


class MatrixConnection:
    """Manages the matrix-nio AsyncClient lifecycle.

    Handles login, event callbacks (messages, invites), sync loop, and bridges
    incoming messages into the agent via dispatch_to_agent().
    """

    DELIVERY_POLL_INTERVAL_S = 10

    def __init__(
        self,
        *,
        db: DbConnection,
        config: MatrixSettings | None = None,
        extra_mcp_servers: dict[str, Any] | None = None,
    ) -> None:
        self._config = config or get_config()
        self._db = db
        self._extra_mcp_servers = extra_mcp_servers or {}
        self._client: AsyncClient | None = None
        self._batch_accumulator: BatchAccumulator | None = None
        self._self_user_id: str = ""
        self._sync_start_time: str = ""

    async def _login(self) -> AsyncClient:
        """Create and authenticate the Matrix client.

        Initialises the crypto store so that E2EE rooms work out of the box.
        On first run, device keys are uploaded to the homeserver.
        """
        cfg = self._config
        cfg.store_path.mkdir(parents=True, exist_ok=True)

        nio_config = ClientConfig(store_sync_tokens=True)
        client = AsyncClient(
            cfg.homeserver,
            cfg.user_id,
            store_path=str(cfg.store_path),
            config=nio_config,
        )

        if cfg.device_id:
            client.device_id = cfg.device_id

        if cfg.access_token:
            client.access_token = cfg.access_token
            client.user_id = cfg.user_id
            if cfg.device_id:
                client.device_id = cfg.device_id
            log.info("Using access token for authentication")
        elif cfg.password:
            resp = await client.login(
                cfg.password,
                device_name=cfg.device_name,
            )
            if isinstance(resp, LoginError):
                msg = f"Login failed: {resp.message}"
                raise RuntimeError(msg)
            log.info("Logged in with password as %s", resp.user_id)
        else:
            msg = (
                "No access_token or password configured. "
                "Set PYKOCLAW_MATRIX_ACCESS_TOKEN or PYKOCLAW_MATRIX_PASSWORD."
            )
            raise RuntimeError(msg)

        self._self_user_id = client.user_id

        # Initialise the Olm crypto store for E2EE support.
        client.load_store()
        log.info("Crypto store loaded (olm=%s)", client.olm is not None)

        # Upload device keys on first run so other clients can encrypt for us.
        if client.should_upload_keys:
            log.info("Uploading device keys...")
            resp = await client.keys_upload()
            log.info("Keys upload: %s", type(resp).__name__)

        return client

    def _register_callbacks(self, client: AsyncClient) -> None:
        """Register event callbacks on the Matrix client."""

        async def on_message(room: MatrixRoom, event: RoomMessageText) -> None:
            await self._handle_message(room, event)

        async def on_invite(room: MatrixRoom, event: InviteMemberEvent) -> None:
            if not self._config.auto_join:
                log.info("Ignoring invite to %s (auto_join disabled)", room.room_id)
                return
            if event.state_key != self._self_user_id:
                return
            log.info("Auto-joining room %s", room.room_id)
            await client.join(room.room_id)

        async def on_megolm(room: MatrixRoom, event: MegolmEvent) -> None:
            log.warning(
                "Unable to decrypt message in %s from %s "
                "(session_id=%s). The sender's client may need to "
                "re-send, or verify this device.",
                room.room_id,
                event.sender,
                event.session_id[:20] if event.session_id else "?",
            )

        client.add_event_callback(on_message, RoomMessageText)
        client.add_event_callback(on_invite, InviteMemberEvent)
        client.add_event_callback(on_megolm, MegolmEvent)

    async def _handle_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Process an incoming room message."""
        try:
            sender = event.sender
            if sender == self._self_user_id:
                return

            text = event.body
            if not text:
                return

            timestamp = datetime.fromtimestamp(
                event.server_timestamp / 1000, tz=timezone.utc
            ).isoformat()

            # Skip old messages from initial sync
            if self._sync_start_time and timestamp < self._sync_start_time:
                log.debug("Skipping old message from %s (ts=%s)", sender, timestamp)
                return

            room_id = room.room_id
            display_name = room.user_name(sender) or sender

            log.info(
                "Message in %s from %s: %s",
                room_id,
                display_name,
                text[:120],
            )

            store_message(
                self._db,
                room_id=room_id,
                sender=display_name,
                text=text,
                timestamp=timestamp,
                is_from_me=False,
            )
            update_room_timestamp(self._db, room_id, timestamp)

            # DM detection: a room with only 2 members (us + them).
            # NOTE: matrix-nio's is_group means "unnamed room" (the opposite
            # of what you'd expect) — DMs are typically unnamed, so is_group
            # is True for DMs. We rely solely on member_count.
            is_dm = room.member_count <= 2
            is_hard_mention = _is_hard_mention(text, self._config.trigger_name)

            log.info(
                "Trigger check: is_dm=%s, is_hard_mention=%s, members=%d",
                is_dm,
                is_hard_mention,
                room.member_count,
            )

            if is_dm or is_hard_mention:
                await self._batch_accumulator.flush_now(room_id)
            else:
                await self._batch_accumulator.add(room_id)
        except Exception:
            log.exception("Error handling Matrix message in %s", room.room_id)

    def _build_system_prompt(self, room_id: str, *, hard_mention: bool) -> str:
        trigger = self._config.trigger_name
        base = dedent(
            f"""\
            You are {trigger}, an ambient participant in a Matrix chat room ({room_id}).

            When you choose to reply, wrap your ENTIRE reply in `<reply>` tags. Text \
            outside these tags will NOT be delivered to the chat. Tool-call reasoning \
            and internal notes must NOT be wrapped in `<reply>` tags.

            You observe conversations silently. In the vast majority of batches, you \
            should produce NO text output. Err heavily toward silence.
            Only reply when: (a) you are directly addressed by name or @mention, \
            (b) there is clear factual misinformation that no one has corrected, or \
            (c) you have crucial missing knowledge that would significantly help the \
            conversation.
            Do NOT volunteer opinions, make small talk, or interject with tangential \
            information. If you choose not to reply, produce no text output at all — \
            do not explain why you are staying silent.
            You may use tools silently (e.g., writing notes, updating files) even \
            when you choose not to reply. Tool use without a reply is normal and expected.
            People may refer to you by name in various forms — your full name, \
            shortened, with or without @, with punctuation, or even inflected/declined \
            forms in non-English languages. When someone addresses you by any variation \
            of your name, treat it as a direct address and reply."""
        )
        if hard_mention:
            base += (
                "\n\nThis batch contains a direct @mention of your name "
                "— you MUST reply to it using `<reply>` tags."
            )
        return base

    async def _handle_agent_trigger(
        self,
        room_id: str,
        hard_mention: bool = False,
    ) -> None:
        """Flush accumulated messages to the agent and deliver the reply."""
        try:
            messages = get_new_messages_for_room(self._db, room_id)
            if not messages:
                return

            xml_context = format_xml_messages(messages)

            system_prompt = self._build_system_prompt(
                room_id, hard_mention=hard_mention
            )

            prompt = (
                f"New message batch from Matrix room:\n\n{xml_context}\n\n"
                f"Decide whether to reply, use tools silently, or do nothing."
            )

            # Show typing indicator while the agent is thinking.
            await self._set_typing(room_id, True)
            try:
                try:
                    result = await dispatch_to_agent(
                        prompt=prompt,
                        channel_prefix="matrix",
                        channel_id=room_id,
                        db=self._db,
                        data_dir=core_settings.data,
                        system_prompt=system_prompt,
                        extra_mcp_servers=self._extra_mcp_servers,
                    )
                except Exception:
                    # Session resume can fail if the previous session state is
                    # corrupt or missing.  Clear the conversation and retry
                    # without resuming.
                    log.exception(
                        "Agent dispatch failed for %s, retrying without session resume",
                        room_id,
                    )
                    from pykoclaw.db import upsert_conversation

                    conv_name = f"matrix-{room_id}"
                    upsert_conversation(
                        self._db, conv_name, "", str(core_settings.data)
                    )

                    result = await dispatch_to_agent(
                        prompt=prompt,
                        channel_prefix="matrix",
                        channel_id=room_id,
                        db=self._db,
                        data_dir=core_settings.data,
                        system_prompt=system_prompt,
                        extra_mcp_servers=self._extra_mcp_servers,
                    )
            finally:
                await self._set_typing(room_id, False)

            extracted = _extract_reply(result.full_text)
            if extracted:
                await self._send_message(room_id, extracted)

                # Store the agent's response locally so it survives session
                # resume failures.  Without this, a failed resume loses all
                # prior agent replies and the XML context only contains human
                # messages.
                now = datetime.now(timezone.utc).isoformat()
                store_message(
                    self._db,
                    room_id=room_id,
                    sender=self._config.trigger_name,
                    text=extracted,
                    timestamp=now,
                    is_from_me=True,
                )

                log.info("Agent response sent to %s", room_id)
            else:
                log.info("Agent chose silence for %s", room_id)

            last_msg_ts = messages[-1][1] if messages else ""
            if last_msg_ts:
                update_agent_cursor(self._db, room_id, last_msg_ts)
        except Exception:
            log.exception("Error in agent trigger for %s", room_id)

    async def _set_typing(self, room_id: str, typing: bool) -> None:
        """Send a typing indicator to a Matrix room."""
        if not self._client:
            return
        try:
            await self._client.room_typing(room_id, typing)
        except Exception:
            log.debug("Failed to send typing indicator to %s", room_id)

    async def _send_message(self, room_id: str, text: str) -> None:
        """Send a formatted message to a Matrix room.

        Converts the Markdown *text* to HTML and sends both plain-text
        (``body``) and rich (``formatted_body``) versions so that clients
        like Element render bold, code blocks, links, etc.

        Uses ``ignore_unverified_devices=True`` so that the bot can send
        to E2EE rooms without requiring manual device verification.
        """
        if not self._client:
            log.warning("Cannot send message — client not connected")
            return
        try:
            content = build_matrix_content(text)
            await self._client.room_send(
                room_id,
                "m.room.message",
                content,
                ignore_unverified_devices=True,
            )
        except Exception:
            log.exception("Failed to send message to %s", room_id)

    async def _delivery_poll_loop(self) -> None:
        """Poll and deliver scheduled task results to Matrix rooms."""
        log.info("Delivery polling started")
        try:
            while True:
                await asyncio.sleep(self.DELIVERY_POLL_INTERVAL_S)
                try:
                    await self._process_pending_deliveries()
                except Exception:
                    log.exception("Error processing delivery queue")
        except asyncio.CancelledError:
            log.info("Delivery polling stopped")

    async def _process_pending_deliveries(self) -> None:
        """Deliver pending messages from the delivery queue."""
        pending = get_pending_deliveries(self._db, "matrix")
        if not pending:
            return

        for delivery in pending:
            room_id = delivery.conversation.removeprefix("matrix-")
            try:
                await self._send_message(room_id, delivery.message)
                mark_delivered(self._db, delivery.id)
                log.info("Delivered task result to %s", room_id)
            except Exception:
                mark_delivery_failed(self._db, delivery.id, "send failed")
                log.exception("Failed to deliver to %s", room_id)

    async def run_async(self) -> None:
        """Start the Matrix client and sync forever (async entry point)."""
        self._sync_start_time = datetime.now(timezone.utc).isoformat()

        self._batch_accumulator = BatchAccumulator(
            window_seconds=self._config.batch_window_seconds,
            flush_callback=self._handle_agent_trigger,
        )

        self._client = await self._login()
        self._register_callbacks(self._client)

        log.info("Starting Matrix sync loop...")

        delivery_task = asyncio.create_task(self._delivery_poll_loop())
        try:
            await self._client.sync_forever(timeout=30000, full_state=True)
        finally:
            delivery_task.cancel()
            try:
                await delivery_task
            except asyncio.CancelledError:
                pass
            await self._client.close()

    def run(self) -> None:
        """Block the main thread on the Matrix sync loop until Ctrl-C."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            log.info("Matrix connection stopped by user")
