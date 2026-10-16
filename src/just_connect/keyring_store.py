"""Optional keyring-backed password storage.

Passwords are never stored on disk in plain text. By default they are kept in
memory only. If the user explicitly opts in and the OS keyring is available,
the password is stored via the ``keyring`` package.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SERVICE_NAME = "just-connect"


def _keyring():
    try:
        import keyring

        return keyring
    except ImportError:
        return None


def get_password(host: str, port: int) -> str | None:
    """Load a remembered password from the OS keyring, if available."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE_NAME, _keyring_username(host, port))
    except Exception as exc:
        logger.warning("Could not read password from keyring: %s", exc)
        return None


def set_password(host: str, port: int, password: str) -> None:
    """Store a password in the OS keyring."""
    kr = _keyring()
    if kr is None:
        logger.warning("keyring package not available; password not stored")
        return
    try:
        kr.set_password(_SERVICE_NAME, _keyring_username(host, port), password)
    except Exception as exc:
        logger.warning("Could not store password in keyring: %s", exc)


def delete_password(host: str, port: int) -> None:
    """Delete a stored password from the OS keyring."""
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(_SERVICE_NAME, _keyring_username(host, port))
    except Exception as exc:
        logger.warning("Could not delete password from keyring: %s", exc)


def _keyring_username(host: str, port: int) -> str:
    return f"vnc://{host}:{port}"
