"""VncBackend implementation using vncdotool."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PIL import Image

from .backend import AuthError, PasswordRequiredError, VncBackend

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# vncdotool is optional for consumers that only use the mock backend or the
# optional C++ backend. Delay the import until this backend is instantiated.
try:
    from twisted.internet import reactor
    from twisted.internet.error import (
        ConnectionDone,
        ConnectionLost,
        ConnectionRefusedError as TwistedConnectionRefused,
    )
    from twisted.python.failure import Failure
    from vncdotool import api as vnc_api
    from vncdotool.client import AuthenticationError
except ImportError as _import_error:  # pragma: no cover
    vnc_api = None  # type: ignore[assignment]
    reactor = None  # type: ignore[assignment]
    AuthenticationError = Exception  # type: ignore[misc, assignment]
    TwistedConnectionRefused = ConnectionRefusedError  # type: ignore[misc, assignment]
    Failure = object  # type: ignore[misc, assignment]
    ConnectionDone = ConnectionLost = Exception  # type: ignore[misc, assignment]


# Map logical key names used by the GUI to vncdotool key names.
_KEY_NAME_MAP = {
    "esc": "esc",
    "escape": "esc",
    "enter": "return",
    "return": "return",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
    "f1": "f1",
    "f2": "f2",
    "f3": "f3",
    "f4": "f4",
    "f5": "f5",
    "f6": "f6",
    "f7": "f7",
    "f8": "f8",
    "f9": "f9",
    "f10": "f10",
    "f11": "f11",
    "f12": "f12",
}

_MODIFIER_MAP = {
    "shift": "shift",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "meta": "meta",
    "command": "meta",
    "win": "meta",
}


def _normalize_key(key: str) -> str:
    """Normalize a logical key name to a vncdotool-compatible key name."""
    lower = key.lower()
    return _KEY_NAME_MAP.get(lower, key)


def _vncdotool_key(key: str, modifiers: list[str] | None) -> str:
    """Build a vncdotool key string such as 'ctrl-shift-c'."""
    parts = []
    if modifiers:
        for mod in modifiers:
            mapped = _MODIFIER_MAP.get(mod.lower(), mod.lower())
            parts.append(mapped)
    parts.append(_normalize_key(key))
    return "-".join(parts)


def _translate_typed_char(char: str) -> str:
    """Translate a typed character to a vncdotool key name."""
    if char == "\n":
        return "return"
    if char == "\r":
        return "return"
    if char == "\t":
        return "tab"
    if char == " ":
        return "space"
    if char == "-":
        return "minus"
    return char


def _type_keys(protocol: object, keys: list[str]) -> None:
    """Press a list of keys; runs on the Twisted reactor thread."""
    for key in keys:
        protocol.keyPress(key)  # type: ignore[attr-defined]


class VncdotoolBackend(VncBackend):
    """VncBackend implemented with vncdotool.

    vncdotool runs the Twisted reactor in a background daemon thread, so all
    networking already happens off the UI thread. This backend is designed to
    be driven from a single worker thread (for example a ``QThread``).
    """

    def __init__(self) -> None:
        if vnc_api is None:  # pragma: no cover
            raise ImportError(
                "vncdotool is required for the vncdotool backend. "
                "Install it with: pip install vncdotool"
            )
        self._proxy: object | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._disconnect_reason: str | None = None
        self._button_mask = 0

    def _mark_disconnected(self, reason: Failure) -> None:
        with self._lock:
            self._connected = False
            self._disconnect_reason = (
                reason.getErrorMessage() if isinstance(reason, Failure) else str(reason)
            )

    def connect(
        self,
        host: str,
        port: int,
        password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        logger.info("Connecting to %s:%d", host, port)
        self._disconnect_reason = None

        try:
            # vncdotool's parse_server uses "host::port" for explicit ports.
            server = f"{host}::{port}"
            # Setting factory.password to None triggers anonymous / no-auth when
            # the server supports it. For VNC password auth, only the password
            # is sent; there is no username field.
            self._proxy = vnc_api.connect(
                server, password=password, timeout=timeout
            )

            # Register a callback so we can detect unexpected drops.
            factory = getattr(self._proxy, "factory", None)
            if factory is not None:
                factory._disconnect_callbacks.append(self._mark_disconnected)

            # Wait for the connection handshake to complete (or fail). A no-op
            # pause is enough to block on the connection deferred.
            self._proxy.pause(0)
        except Exception as exc:
            self._proxy = None
            mapped = self._map_exception(exc)
            logger.warning("Connection to %s:%d failed: %s", host, port, mapped)
            raise mapped from exc

        with self._lock:
            self._connected = True
        logger.info("Connected to %s:%d", host, port)

    def disconnect(self) -> None:
        if self._proxy is None:
            return
        try:
            self._proxy.disconnect()
        except Exception as exc:  # pragma: no cover
            logger.debug("disconnect raised %s", exc)
        with self._lock:
            self._connected = False
        self._proxy = None

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._proxy is not None

    def _protocol(self) -> object | None:
        """Return the live vncdotool protocol, or None when not connected."""
        proxy = self._proxy
        if proxy is None:
            return None
        return getattr(proxy, "protocol", None)

    @staticmethod
    def _call_soon(method: object, *args: object, **kwargs: object) -> None:
        """Schedule a protocol call on the Twisted reactor thread.

        Unlike the vncdotool proxy calls, this never blocks waiting for a
        result, so slow framebuffer traffic can never delay keyboard/mouse
        input or freeze the worker thread.
        """
        try:
            reactor.callFromThread(method, *args, **kwargs)
        except Exception as exc:
            logger.debug("reactor call failed: %s", exc)

    def get_frame(self) -> Image | None:
        protocol = self._protocol()
        if protocol is None:
            return None
        # Ask the server for fresh pixels without blocking; the reactor thread
        # pastes incoming rectangles into protocol.screen as they arrive.
        self._call_soon(protocol.framebufferUpdateRequest, incremental=1)
        screen = getattr(protocol, "screen", None)
        if screen is None:
            return None
        try:
            # Copy so the reactor can keep pasting into the original image.
            return screen.copy()
        except Exception:
            # The reactor may mutate the image mid-copy; just skip this frame.
            return None

    def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        protocol = self._protocol()
        if protocol is None:
            return
        vnc_key = _vncdotool_key(key, modifiers)
        logger.debug("send_key %s", vnc_key)
        self._call_soon(protocol.keyPress, vnc_key)

    def send_text(self, text: str) -> None:
        protocol = self._protocol()
        if protocol is None:
            return
        logger.debug("send_text %r", text[:20])
        keys = [_translate_typed_char(char) for char in text]
        self._call_soon(_type_keys, protocol, keys)

    def send_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        protocol = self._protocol()
        if protocol is None:
            return
        logger.debug("send_pointer_event %d,%d mask=%d", x, y, button_mask)
        self._call_soon(self._apply_pointer, protocol, x, y, button_mask)

    def _apply_pointer(self, protocol: object, x: int, y: int, button_mask: int) -> None:
        """Apply pointer state; runs on the reactor thread."""
        protocol.mouseMove(x, y)
        changed = self._button_mask ^ button_mask
        for bit in range(3):
            button = bit + 1
            mask = 1 << bit
            if changed & mask:
                if button_mask & mask:
                    protocol.mouseDown(button)
                else:
                    protocol.mouseUp(button)
        self._button_mask = button_mask

    def _map_exception(self, exc: Exception) -> Exception:
        """Map a vncdotool/Twisted exception to a typed exception."""
        if isinstance(exc, AuthenticationError):
            message = str(exc).lower()
            if "password required" in message:
                return PasswordRequiredError(str(exc))
            return AuthError(str(exc))
        if isinstance(exc, TwistedConnectionRefused):
            return ConnectionRefusedError("Connection refused to VNC server")
        if isinstance(exc, (ConnectionDone, ConnectionLost)):
            return ConnectionError(str(exc))
        return exc

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.disconnect()
        except Exception:
            pass
