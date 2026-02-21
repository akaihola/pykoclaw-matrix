"""Tests for MatrixSettings configuration and .env file loading."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pykoclaw_matrix.config import MatrixSettings


class TestMatrixSettingsDefaults:
    """Test MatrixSettings default values in isolated environment."""

    def test_defaults_no_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings uses defaults when no .env file exists."""
        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.homeserver == "https://matrix.org"
        assert settings.user_id == ""
        assert settings.access_token == ""
        assert settings.password == ""
        assert settings.device_name == "pykoclaw"
        assert settings.trigger_name == "Andy"
        assert settings.batch_window_seconds == 90
        assert settings.auto_join is True

    def test_store_path_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings.store_path default path."""
        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        expected = Path.home() / ".local" / "share" / "pykoclaw" / "matrix" / "store"
        assert settings.store_path == expected


class TestMatrixSettingsEnvFileLoading:
    """Test MatrixSettings loads from .env file in CWD."""

    def test_loads_homeserver_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings loads PYKOCLAW_MATRIX_HOMESERVER from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MATRIX_HOMESERVER=https://my.server\n")

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.homeserver == "https://my.server"

    def test_loads_trigger_name_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings loads PYKOCLAW_MATRIX_TRIGGER_NAME from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MATRIX_TRIGGER_NAME=Bot\n")

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.trigger_name == "Bot"

    def test_loads_batch_window_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings loads PYKOCLAW_MATRIX_BATCH_WINDOW_SECONDS from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MATRIX_BATCH_WINDOW_SECONDS=120\n")

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.batch_window_seconds == 120

    def test_loads_multiple_vars_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings loads multiple PYKOCLAW_MATRIX_* vars from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            dedent("""\
                PYKOCLAW_MATRIX_HOMESERVER=https://my.server
                PYKOCLAW_MATRIX_USER_ID=@bot:my.server
                PYKOCLAW_MATRIX_TRIGGER_NAME=MyBot
                PYKOCLAW_MATRIX_BATCH_WINDOW_SECONDS=60
                PYKOCLAW_MATRIX_AUTO_JOIN=false
                """)
        )

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.homeserver == "https://my.server"
        assert settings.user_id == "@bot:my.server"
        assert settings.trigger_name == "MyBot"
        assert settings.batch_window_seconds == 60
        assert settings.auto_join is False


class TestMatrixSettingsEnvVarOverride:
    """Test environment variables override .env file values."""

    def test_env_var_overrides_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test env var PYKOCLAW_MATRIX_TRIGGER_NAME overrides .env value."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MATRIX_TRIGGER_NAME=FromFile\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYKOCLAW_MATRIX_TRIGGER_NAME", "FromEnvVar")

        settings = MatrixSettings()

        assert settings.trigger_name == "FromEnvVar"

    def test_env_var_overrides_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test env var PYKOCLAW_MATRIX_HOMESERVER overrides default."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYKOCLAW_MATRIX_HOMESERVER", "https://custom.server")

        settings = MatrixSettings()

        assert settings.homeserver == "https://custom.server"


class TestMatrixSettingsIgnoresWrongPrefix:
    """Test MatrixSettings ignores env vars with wrong prefix."""

    def test_ignores_pykoclaw_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings silently ignores PYKOCLAW_MODEL (wrong prefix)."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MODEL=should-be-ignored\n")

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.trigger_name == "Andy"

    def test_ignores_whatsapp_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test MatrixSettings ignores PYKOCLAW_WA_TRIGGER_NAME."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_WA_TRIGGER_NAME=should-be-ignored\n")

        monkeypatch.chdir(tmp_path)

        settings = MatrixSettings()

        assert settings.trigger_name == "Andy"
