"""Safe logging setup for just-connect.

Passwords and frame pixel data are never logged. Only host, port, connection
status, and high-level user actions are recorded.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure a safe console logger for the application."""
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if configure_logging is called more than once.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    # vncdotool can be chatty; keep it at INFO by default.
    logging.getLogger("vncdotool").setLevel(logging.WARNING)
