"""Persistent application configuration.

Only host, port, and the selected backend are persisted. Passwords are never
stored on disk.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

BackendName = Literal["vncdotool", "tinyvnc"]


@dataclass
class AppConfig:
    host: str = ""
    port: int = 5900
    backend: BackendName = "vncdotool"
    fps: int = 1


_CONFIG_FILE_NAME = "config.json"


def _config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.name == "posix":
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    else:
        base = Path.home()
    return base / "just-connect"


def _config_path() -> Path:
    path = _config_dir() / _CONFIG_FILE_NAME
    return path


def load_config() -> AppConfig:
    path = _config_path()
    if not path.exists():
        logger.debug("No config file at %s; using defaults", path)
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Only load keys we explicitly persist; ignore anything else.
        return AppConfig(
            host=data.get("host", ""),
            port=int(data.get("port", 5900)),
            backend=data.get("backend", "vncdotool"),
            fps=int(data.get("fps", 1)),
        )
    except Exception as exc:
        logger.warning("Failed to load config from %s: %s", path, exc)
        return AppConfig()


def save_config(config: AppConfig) -> None:
    path = _config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(config), indent=2) + "\n",
            encoding="utf-8",
        )
        logger.debug("Saved config to %s", path)
    except Exception as exc:
        logger.warning("Failed to save config to %s: %s", path, exc)
