"""Matrix plugin configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

_DEFAULT_DATA = Path.home() / ".local" / "share" / "pykoclaw"


def _resolve_data_dir() -> Path:
    """Resolve the pykoclaw data directory from ``PYKOCLAW_DATA`` env var."""
    return Path(os.environ.get("PYKOCLAW_DATA", str(_DEFAULT_DATA)))


class MatrixSettings(BaseSettings):
    """Matrix plugin configuration.

    All settings can be set via environment variables with the
    ``PYKOCLAW_MATRIX_`` prefix, or via ``.env`` file located in the
    pykoclaw data directory (``PYKOCLAW_DATA``) or the current working
    directory.
    """

    homeserver: str = Field(default="https://matrix.org")
    user_id: str = Field(default="")
    access_token: str = Field(default="")
    password: str = Field(default="")
    device_name: str = Field(default="pykoclaw")
    device_id: str = Field(default="")
    store_path: Path = Field(
        default_factory=lambda: _resolve_data_dir() / "matrix" / "store"
    )
    trigger_name: str = Field(default="Andy")
    batch_window_seconds: int = Field(default=90)
    auto_join: bool = Field(default=True)
    extra_db_paths: list[Path] = Field(
        default_factory=list,
        description=(
            "Additional pykoclaw.db paths to poll for ``channel_prefix='matrix'`` "
            "delivery queue entries.  This lets agents that don't have their own "
            "Matrix connection send messages via *this* service's bot account.  "
            "Example: ``PYKOCLAW_MATRIX_EXTRA_DB_PATHS="
            '\'["/home/agent/pipsa/pykoclaw.db"]\' '
            "allows Ressu (pipsa) to deliver scheduled task results to Matrix "
            "rooms through Tyko's ``@tyko-agent:matrix.org`` connection."
        ),
    )

    model_config = {
        "env_prefix": "PYKOCLAW_MATRIX_",
        "env_file": (
            str(_resolve_data_dir() / ".env"),
            str(_DEFAULT_DATA / ".env"),
            ".env",
        ),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


_config: MatrixSettings | None = None


def get_config() -> MatrixSettings:
    """Get Matrix plugin configuration (cached singleton)."""
    global _config
    if _config is None:
        _config = MatrixSettings()
    return _config
