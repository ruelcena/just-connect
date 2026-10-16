"""VncBackend implementation that wraps TinyVNC through pybind11.

This backend is optional. If ``just_connect._tinyvnc`` is not built, the GUI
falls back to the vncdotool backend. To build it:

    pip install .[tinyvnc]

or:

    python src/just_connect/tinyvnc_build/setup.py build_ext --inplace
"""

from __future__ import annotations

import logging
import struct
import time
from typing import TYPE_CHECKING

from PIL import Image

from .backend import AuthError, PasswordRequiredError, VncBackend

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

try:
    from just_connect import _tinyvnc
except ImportError as _import_error:  # pragma: no cover
    _tinyvnc = None  # type: ignore[assignment]


# Map logical key names used by the GUI to X11 keysym values.
# These match the constants in TinyVNC's keysymdef.h.
_KEY_NAME_MAP = {
    "esc": 0xFF1B,
    "escape": 0xFF1B,
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "space": 0x0020,
    "backspace": 0xFF08,
    "delete": 0xFFFF,
    "del": 0xFFFF,
    "insert": 0xFF63,
    "home": 0xFF50,
    "end": 0xFF57,
    "pageup": 0xFF55,
    "pagedown": 0xFF56,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "f1": 0xFFBE,
    "f2": 0xFFBF,
    "f3": 0xFFC0,
    "f4": 0xFFC1,
    "f5": 0xFFC2,
    "f6": 0xFFC3,
    "f7": 0xFFC4,
    "f8": 0xFFC5,
    "f9": 0xFFC6,
    "f10": 0xFFC7,
    "f11": 0xFFC8,
    "f12": 0xFFC9,
}


def _keysym_for_char(char: str) -> int:
    """Return an X11 keysym for a typed character."""
    if len(char) == 1:
        code = ord(char)
        # Printable ASCII maps directly.
        if 0x20 <= code <= 0x7E:
            return code
    return 0


def _keysym_for_key(key: str) -> int:
    """Return an X11 keysym for a logical key name."""
    lower = key.lower()
    if lower in _KEY_NAME_MAP:
        return _KEY_NAME_MAP[lower]
    if len(key) == 1:
        return _keysym_for_char(key)
    return 0


class TinyVncBackend(VncBackend):
    """VncBackend implemented on top of TinyVNC's C++ client.

    The TinyVNC client is single-threaded and driven by repeated calls to
    ``update()``. This backend is designed to be called from a dedicated
    worker thread (for example a ``QThread``).
    """

    def __init__(self) -> None:
        if _tinyvnc is None:  # pragma: no cover
            raise ImportError(
                "The TinyVNC backend is not built. "
                "Build it with: pip install .[tinyvnc]"
            )
        self._client = None
        self._host: str | None = None
        self._port: int | None = None
        self._password: str | None = None

    def connect(
        self,
        host: str,
        port: int,
        password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        logger.info("Connecting to %s:%d via TinyVNC", host, port)
        self._host = host
        self._port = port
        self._password = password

        self._client = _tinyvnc.VncClient(host, str(port))
        if password:
            self._client.set_password(password)
        self._client.set_keep_framebuffer(True)

        deadline = time.monotonic() + timeout
        while not self._client.connected():
            remaining = max(0.001, deadline - time.monotonic())
            if not self._client.update(remaining):
                break
            if time.monotonic() >= deadline:
                break

        if not self._client.connected():
            code = self._client.error_code()
            description = self._client.error_description()
            self._client = None
            logger.warning("TinyVNC connection failed: %s (%d)", description, code)
            if code == _tinyvnc.STREAM_VNC_PASSWORD_REQUIRED:
                raise PasswordRequiredError(description)
            if code == _tinyvnc.STREAM_VNC_LOGIN_FAILED:
                raise AuthError(description)
            if code == _tinyvnc.STREAM_TCP_ERROR:
                if "refused" in description.lower():
                    raise ConnectionRefusedError(description)
                raise TimeoutError(description)
            raise ConnectionError(description)

        logger.info("Connected to %s:%d via TinyVNC", host, port)

    def disconnect(self) -> None:
        if self._client is not None:
            self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.connected()

    def _pump(self, timeout: float = 0.5) -> None:
        """Pump the TinyVNC state machine for up to ``timeout`` seconds."""
        if self._client is None:
            return
        deadline = time.monotonic() + timeout
        while self._client.connected() and time.monotonic() < deadline:
            self._client.update(0.05)

    def get_frame(self) -> Image | None:
        if self._client is None:
            return None
        width = self._client.framebuffer_width()
        height = self._client.framebuffer_height()
        bpp = self._client.framebuffer_bpp()
        if width <= 0 or height <= 0 or bpp <= 0:
            return None

        # Request a full, non-incremental update of the whole screen.
        self._client.request_screen(False, 0, 0, width, height)
        self._pump(2.0)

        data = self._client.framebuffer()
        if not data:
            return None

        expected = width * height * bpp
        if len(data) < expected:
            return None

        # TinyVNC stores the framebuffer as 32-bit RGBX.
        if bpp == 4:
            return Image.frombytes("RGBX", (width, height), data[:expected]).convert(
                "RGB"
            )
        if bpp == 3:
            return Image.frombytes("RGB", (width, height), data[:expected])
        if bpp == 2:
            return Image.frombytes("BGR;16", (width, height), data[:expected]).convert(
                "RGB"
            )
        return None

    def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        if self._client is None:
            return
        keysym = _keysym_for_key(key)
        if keysym == 0:
            logger.warning("Unknown key: %s", key)
            return

        if modifiers:
            modifier_keysyms = []
            for mod in modifiers:
                mod_lower = mod.lower()
                if mod_lower in ("shift",):
                    modifier_keysyms.append(0xFFE1)
                elif mod_lower in ("ctrl", "control"):
                    modifier_keysyms.append(0xFFE3)
                elif mod_lower in ("alt",):
                    modifier_keysyms.append(0xFFE9)
                elif mod_lower in ("meta", "command", "win"):
                    modifier_keysyms.append(0xFFEB)

            for mk in modifier_keysyms:
                self._client.send_key(mk, True)
            self._client.send_key(keysym, True)
            self._client.send_key(keysym, False)
            for mk in reversed(modifier_keysyms):
                self._client.send_key(mk, False)
        else:
            self._client.pulse_key(keysym)

        self._pump(0.1)

    def send_text(self, text: str) -> None:
        if self._client is None:
            return
        for char in text:
            keysym = _keysym_for_char(char)
            if keysym:
                self._client.pulse_key(keysym)
            else:
                # Fallback for non-ASCII characters: try the key name map.
                keysym = _keysym_for_key(char)
                if keysym:
                    self._client.pulse_key(keysym)
        self._pump(0.1)

    def send_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        # TinyVNC's VncClient does not expose a direct pointer-event method.
        # This backend focuses on keyboard / screen capture; pointer events are
        # left as no-ops. The vncdotool backend provides full mouse support.
        logger.debug("TinyVNC backend does not implement pointer events")
