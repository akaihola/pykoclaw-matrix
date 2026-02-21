"""Matrix plugin configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class MatrixSettings(BaseSettings):
    """Matrix plugin configuration.

    All settings can be set via environment variables with the
    ``PYKOCLAW_MATRIX_`` prefix, or via ``.env`` file.
    """

    homeserver: str = Field(default="https://matrix.org")
    user_id: str = Field(default="")
    access_token: str = Field(default="")
    password: str = Field(default="")
    device_name: str = Field(default="pykoclaw")
    device_id: str = Field(default="")
    store_path: Path = Field(
        default=Path.home() / ".local" / "share" / "pykoclaw" / "matrix" / "store"
    )
    trigger_name: str = Field(default="Andy")
    batch_window_seconds: int = Field(default=90)
    auto_join: bool = Field(default=True)

    model_config = {
        "env_prefix": "PYKOCLAW_MATRIX_",
        "env_file": (
            str(Path.home() / ".local" / "share" / "pykoclaw" / ".env"),
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
