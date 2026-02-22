"""Matrix/Element plugin for pykoclaw."""

from __future__ import annotations

import os
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Callable

import click
from pydantic_settings import BaseSettings

from pykoclaw.db import DbConnection
from pykoclaw.plugins import PykoClawPluginBase

from .config import MatrixSettings

if TYPE_CHECKING:
    from .config import MatrixSettings as _MatrixSettings


def _bootstrap_cross_signing(
    mx: _MatrixSettings, encode_canonical_json: Callable[[dict], bytes]
) -> None:
    """Reset cross-signing keys and sign the current device.

    This removes the red "unverified device" warning in Element by
    making the bot's account vouch for its own device via cross-signing.
    """
    import olm.pk

    import httpx

    master = olm.pk.PkSigning(os.urandom(32))
    self_signing = olm.pk.PkSigning(os.urandom(32))
    user_signing = olm.pk.PkSigning(os.urandom(32))

    click.echo(
        f"Generated new cross-signing keys (master: {master.public_key[:16]}...)"
    )

    def _sign(signing_key: Any, obj: dict, uid: str, key_id: str) -> dict:
        stripped = {k: v for k, v in obj.items() if k not in ("signatures", "unsigned")}
        sig = signing_key.sign(encode_canonical_json(stripped))
        obj.setdefault("signatures", {}).setdefault(uid, {})[key_id] = sig
        return obj

    master_obj = {
        "keys": {f"ed25519:{master.public_key}": master.public_key},
        "usage": ["master"],
        "user_id": mx.user_id,
    }
    ss_obj = {
        "keys": {f"ed25519:{self_signing.public_key}": self_signing.public_key},
        "usage": ["self_signing"],
        "user_id": mx.user_id,
    }
    _sign(master, ss_obj, mx.user_id, f"ed25519:{master.public_key}")

    us_obj = {
        "keys": {f"ed25519:{user_signing.public_key}": user_signing.public_key},
        "usage": ["user_signing"],
        "user_id": mx.user_id,
    }
    _sign(master, us_obj, mx.user_id, f"ed25519:{master.public_key}")

    body: dict[str, Any] = {
        "master_key": master_obj,
        "self_signing_key": ss_obj,
        "user_signing_key": us_obj,
    }

    hs = mx.homeserver.rstrip("/")
    headers = {"Authorization": f"Bearer {mx.access_token}"}
    client = httpx.Client()

    # Step 1: initiate upload to discover UIA requirements
    r = client.post(
        f"{hs}/_matrix/client/v3/keys/device_signing/upload", headers=headers, json=body
    )

    if r.status_code == 401:
        data = r.json()
        session = data.get("session", "")
        params = data.get("params", {})

        reset_params = params.get("org.matrix.cross_signing_reset", {})
        reset_url = reset_params.get("url", "")

        if reset_url:
            click.echo("")
            click.echo("=" * 60)
            click.echo("Matrix server requires web approval for cross-signing reset.")
            click.echo("Open this URL in a browser and approve the reset:")
            click.echo(f"\n  {reset_url}\n")
            click.echo("=" * 60)
            click.echo("")
            input("Press Enter AFTER you have approved the reset in the browser...")

            body["auth"] = {
                "type": "org.matrix.cross_signing_reset",
                "session": session,
            }
        else:
            # Fallback: try password auth
            password = click.prompt("Matrix account password", hide_input=True)
            body["auth"] = {
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": mx.user_id},
                "password": password,
                "session": session,
            }

        r2 = client.post(
            f"{hs}/_matrix/client/v3/keys/device_signing/upload",
            headers=headers,
            json=body,
        )
        if r2.status_code != 200:
            click.echo(f"✗ Upload failed: {r2.status_code} {r2.text[:300]}", err=True)
            raise SystemExit(1)
        click.echo("✓ Cross-signing keys uploaded!")

    elif r.status_code == 200:
        click.echo("✓ Cross-signing keys uploaded!")
    else:
        click.echo(f"✗ Unexpected response: {r.status_code} {r.text[:300]}", err=True)
        raise SystemExit(1)

    # Step 2: sign our device with the self-signing key
    r3 = client.post(
        f"{hs}/_matrix/client/v3/keys/query",
        headers=headers,
        json={"device_keys": {mx.user_id: [mx.device_id]}},
    )
    dk = r3.json()["device_keys"][mx.user_id][mx.device_id]

    dev_obj = {
        "algorithms": dk["algorithms"],
        "device_id": mx.device_id,
        "keys": dk["keys"],
        "user_id": mx.user_id,
    }
    _sign(self_signing, dev_obj, mx.user_id, f"ed25519:{self_signing.public_key}")

    r4 = client.post(
        f"{hs}/_matrix/client/v3/keys/signatures/upload",
        headers=headers,
        json={mx.user_id: {mx.device_id: dev_obj}},
    )
    if r4.status_code == 200:
        click.echo(f"✓ Device {mx.device_id} cross-signed!")
        click.echo("  Red warning icons should disappear on new messages.")
    else:
        click.echo(
            f"✗ Signature upload failed: {r4.status_code} {r4.text[:300]}",
            err=True,
        )


class MatrixPlugin(PykoClawPluginBase):
    """Matrix/Element plugin for pykoclaw."""

    def register_commands(self, group: click.Group) -> None:
        @group.group()
        def matrix() -> None:
            """Matrix/Element integration commands."""

        @matrix.command()
        def run() -> None:
            """Run Matrix message listener."""
            import logging

            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(name)s %(levelname)s %(message)s",
            )

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

            if not mx_config.user_id:
                click.echo("✗ PYKOCLAW_MATRIX_USER_ID is not set.", err=True)
                click.echo(
                    "  Run 'pykoclaw matrix login' to get credentials,",
                    err=True,
                )
                click.echo(
                    "  then add them to your .env file.",
                    err=True,
                )
                raise SystemExit(1)

            if not mx_config.access_token and not mx_config.password:
                click.echo(
                    "✗ No credentials configured. Set "
                    "PYKOCLAW_MATRIX_ACCESS_TOKEN or PYKOCLAW_MATRIX_PASSWORD.",
                    err=True,
                )
                click.echo(
                    "  Run 'pykoclaw matrix login' to get an access token.",
                    err=True,
                )
                raise SystemExit(1)

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

        @matrix.command()
        def verify() -> None:
            """Cross-sign the bot's device to remove red warning icons.

            Resets cross-signing keys on the Matrix server and signs the
            current device.  Matrix.org requires approving the reset via
            a web browser — the command prints the URL and waits for
            confirmation.

            Requires PYKOCLAW_MATRIX_ACCESS_TOKEN and
            PYKOCLAW_MATRIX_DEVICE_ID to be set (run ``login`` first).
            """
            from .config import get_config

            mx = get_config()
            if not mx.access_token or not mx.device_id:
                click.echo(
                    "✗ PYKOCLAW_MATRIX_ACCESS_TOKEN and "
                    "PYKOCLAW_MATRIX_DEVICE_ID must be set.",
                    err=True,
                )
                click.echo(
                    "  Run 'pykoclaw matrix login' first.",
                    err=True,
                )
                raise SystemExit(1)

            try:
                import olm.pk  # noqa: F401
            except ImportError:
                click.echo(
                    "✗ python-olm with encryption support is required.",
                    err=True,
                )
                raise SystemExit(1)

            try:
                from canonicaljson import encode_canonical_json
            except ImportError:
                click.echo(
                    "✗ canonicaljson is required. "
                    "Install with: uv pip install canonicaljson",
                    err=True,
                )
                raise SystemExit(1)

            _bootstrap_cross_signing(mx, encode_canonical_json)

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
