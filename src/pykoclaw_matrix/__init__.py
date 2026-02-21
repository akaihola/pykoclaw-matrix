"""Matrix/Element plugin for pykoclaw."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

import click
from pydantic_settings import BaseSettings

from pykoclaw.db import DbConnection
from pykoclaw.plugins import PykoClawPluginBase

from .config import MatrixSettings


class MatrixPlugin(PykoClawPluginBase):
    """Matrix/Element plugin for pykoclaw."""

    def register_commands(self, group: click.Group) -> None:
        @group.group()
        def matrix() -> None:
            """Matrix/Element integration commands."""

        @matrix.command()
        def run() -> None:
            """Run Matrix message listener."""
            from pykoclaw.config import settings
            from pykoclaw.db import init_db
            from pykoclaw.plugins import run_db_migrations

            from .connection import MatrixConnection

            db = init_db(settings.db_path)
            db.execute("PRAGMA journal_mode=WAL")

            plugin = MatrixPlugin()
            run_db_migrations(db, [plugin])

            mcp_servers = plugin.get_mcp_servers(db, "matrix")

            from .config import get_config

            mx_config = get_config()
            click.echo(f"Data directory: {settings.data}")
            click.echo(f"Homeserver:     {mx_config.homeserver}")
            click.echo(f"User ID:        {mx_config.user_id}")
            click.echo(f"Trigger name:   {mx_config.trigger_name}")

            conn = MatrixConnection(db=db, extra_mcp_servers=mcp_servers)
            conn.run()

        @matrix.command()
        def status() -> None:
            """Check Matrix connection status."""
            click.echo("Matrix status check not yet implemented")

        @matrix.command()
        @click.option("--homeserver", prompt=True, help="Matrix homeserver URL")
        @click.option("--user-id", prompt=True, help="Matrix user ID (@user:server)")
        @click.option(
            "--password",
            prompt=True,
            hide_input=True,
            help="Matrix account password",
        )
        def login(homeserver: str, user_id: str, password: str) -> None:
            """Login to Matrix and print an access token for configuration."""
            import asyncio

            async def _do_login() -> None:
                from nio import AsyncClient, LoginError

                client = AsyncClient(homeserver, user_id)
                try:
                    resp = await client.login(password, device_name="pykoclaw")
                    if isinstance(resp, LoginError):
                        click.echo(f"\n✗ Login failed: {resp.message}")
                        raise SystemExit(1)
                    click.echo("\n✓ Login successful!")
                    click.echo(f"  User ID:      {resp.user_id}")
                    click.echo(f"  Device ID:    {resp.device_id}")
                    click.echo(f"  Access Token: {resp.access_token}")
                    click.echo(
                        dedent("""\

                        Add these to your .env file:
                          PYKOCLAW_MATRIX_HOMESERVER={homeserver}
                          PYKOCLAW_MATRIX_USER_ID={user_id}
                          PYKOCLAW_MATRIX_ACCESS_TOKEN={token}
                          PYKOCLAW_MATRIX_DEVICE_ID={device_id}
                        """).format(
                            homeserver=homeserver,
                            user_id=resp.user_id,
                            token=resp.access_token,
                            device_id=resp.device_id,
                        )
                    )
                finally:
                    await client.close()

            asyncio.run(_do_login())

    def get_db_migrations(self) -> list[str]:
        return [
            dedent("""\
                CREATE TABLE IF NOT EXISTS matrix_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    sender TEXT,
                    text TEXT,
                    timestamp TEXT NOT NULL,
                    is_from_me INTEGER DEFAULT 0
                )"""),
            dedent("""\
                CREATE TABLE IF NOT EXISTS matrix_rooms (
                    room_id TEXT PRIMARY KEY,
                    name TEXT,
                    last_timestamp TEXT,
                    last_agent_timestamp TEXT
                )"""),
        ]

    def get_config_class(self) -> type[BaseSettings] | None:
        return MatrixSettings

    def get_mcp_servers(self, db: DbConnection, conversation: str) -> dict[str, Any]:
        from claude_agent_sdk import create_sdk_mcp_server, tool

        from .handler import format_xml_messages, get_new_messages_for_room

        @tool(
            "send_matrix_message",
            dedent("""\
                Send a message to a Matrix room.
                The room_id is in format '!roomid:server'."""),
            {"room_id": str, "text": str},
        )
        async def send_matrix_message(args: dict[str, Any]) -> dict[str, Any]:
            room_id = args["room_id"]
            text = args["text"]
            db.execute(
                dedent("""\
                    INSERT INTO matrix_messages
                        (room_id, sender, text, timestamp, is_from_me)
                    VALUES (?, ?, ?, datetime('now'), 1)"""),
                (room_id, "assistant", text),
            )
            db.commit()
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Message queued for {room_id} ({len(text)} chars)",
                    }
                ]
            }

        @tool(
            "get_matrix_history",
            "Get recent messages from a Matrix room.",
            {"room_id": str},
        )
        async def get_matrix_history(args: dict[str, Any]) -> dict[str, Any]:
            messages = get_new_messages_for_room(db, args["room_id"])
            if not messages:
                return {"content": [{"type": "text", "text": "No new messages."}]}
            xml = format_xml_messages(messages)
            return {"content": [{"type": "text", "text": xml}]}

        return {
            "matrix": create_sdk_mcp_server(
                name="matrix",
                tools=[send_matrix_message, get_matrix_history],
            )
        }
