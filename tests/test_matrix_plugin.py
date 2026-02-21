"""Tests for the Matrix plugin."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
import pytest

from pykoclaw_matrix import MatrixPlugin
from pykoclaw_matrix.config import MatrixSettings


def test_matrix_plugin_implements_protocol() -> None:
    """Test that MatrixPlugin implements PykoClawPlugin protocol."""
    from pykoclaw.plugins import PykoClawPlugin

    plugin = MatrixPlugin()
    assert isinstance(plugin, PykoClawPlugin)


def test_register_commands_adds_matrix_group() -> None:
    """Test that register_commands adds matrix command group."""
    plugin = MatrixPlugin()
    group = click.Group()

    plugin.register_commands(group)

    assert "matrix" in group.commands
    matrix_group = group.commands["matrix"]
    assert isinstance(matrix_group, click.Group)


def test_matrix_group_has_subcommands() -> None:
    """Test that matrix group has login, run, and status subcommands."""
    plugin = MatrixPlugin()
    group = click.Group()

    plugin.register_commands(group)

    matrix_group = group.commands["matrix"]
    assert "login" in matrix_group.commands
    assert "run" in matrix_group.commands
    assert "status" in matrix_group.commands


def test_get_db_migrations_returns_valid_sql() -> None:
    """Test that get_db_migrations returns valid SQL statements."""
    plugin = MatrixPlugin()
    migrations = plugin.get_db_migrations()

    assert len(migrations) == 2
    assert "CREATE TABLE IF NOT EXISTS matrix_messages" in migrations[0]
    assert "CREATE TABLE IF NOT EXISTS matrix_rooms" in migrations[1]

    db = sqlite3.connect(":memory:")
    for sql in migrations:
        db.executescript(sql)

    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "matrix_messages" in tables
    assert "matrix_rooms" in tables


def test_get_config_class_returns_matrix_settings() -> None:
    """Test that get_config_class returns MatrixSettings."""
    plugin = MatrixPlugin()
    config_cls = plugin.get_config_class()

    assert config_cls is not None
    assert config_cls is MatrixSettings


def test_get_mcp_servers_returns_matrix_server() -> None:
    """Test that get_mcp_servers returns matrix MCP server."""
    plugin = MatrixPlugin()
    db = sqlite3.connect(":memory:")

    servers = plugin.get_mcp_servers(db, "test")

    assert "matrix" in servers
    assert isinstance(servers["matrix"], dict)


def test_matrix_settings_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test MatrixSettings default values."""
    monkeypatch.chdir(tmp_path)

    settings = MatrixSettings()

    assert settings.trigger_name == "Andy"
    assert settings.homeserver == "https://matrix.org"
    assert settings.batch_window_seconds == 90
    assert settings.auto_join is True
    assert "matrix" in str(settings.store_path)
