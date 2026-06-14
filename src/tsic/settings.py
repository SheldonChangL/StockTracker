"""Path and environment configuration shared across layers.

Secrets are read from the environment only; no plaintext key is ever stored
in this module or any config file.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Root directory for tsic-managed local state.
APP_DIR = Path.home() / ".tsic"

#: Environment variable holding the Fugle API key.
FUGLE_API_KEY_ENV = "TSIC_FUGLE_API_KEY"


def default_db_path() -> Path:
    """Return the default SQLite database path (``~/.tsic/data.db``)."""
    return APP_DIR / "data.db"


def log_path() -> Path:
    """Return the default log file path (``~/.tsic/tsic.log``)."""
    return APP_DIR / "tsic.log"


def fugle_api_key() -> str | None:
    """Return the Fugle API key from the environment, or ``None`` if unset."""
    return os.environ.get(FUGLE_API_KEY_ENV)
