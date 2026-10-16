"""VncWorker: runs a VncBackend on a QThread and talks to the GUI via signals."""

from __future__ import annotations

import logging
import queue
import time
from typing import TYPE_CHECKING

from PySide6 import QtCore

from .backend import AuthError, PasswordRequiredError, VncBackend
from .config import BackendName
from .vncdotool_backend import VncdotoolBackend

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)


def create_backend(name: BackendName) -> VncBackend:
    """Instantiate a VncBackend by name, falling back to vncdotool."""
    if name == "tinyvnc":
        try:
            from .tinyvnc_backend import TinyVncBackend

            return TinyVncBackend()
        except ImportError as exc:
            logger.warning(
                "TinyVNC backend unavailable (%s); using vncdotool backend", exc
            )
            return VncdotoolBackend()
    return VncdotoolBackend()


class _Command:
    """Base class for commands sent to the worker thread."""

    pass


class _ConnectCommand(_Command):
    def __init__(self, host: str, port: int, password: str | None) -> None:
        self.host = host
        self.port = port
        self.password = password


class _DisconnectCommand(_Command):
    pass


class _KeyCommand(_Command):
    def __init__(self, key: str, modifiers: list[str] | None) -> None:
        self.key = key
        self.modifiers = modifiers


class _TextCommand(_Command):
    def __init__(self, text: str) -> None:
        self.text = text


class _PointerCommand(_Command):
    def __init__(self, x: int, y: int, button_mask: int) -> None:
        self.x = x
        self.y = y
        self.button_mask = button_mask


class _SetFpsCommand(_Command):
    def __init__(self, fps: int) -> None:
        self.fps = fps


class VncWorker(QtCore.QThread):
    """Thread that owns a VncBackend and feeds the UI with frames and status.

    All public methods are safe to call from the UI thread. They enqueue work
    and return immediately.
    """

    # Python objects travel fine through PySide6 queued signals.
    frame_ready = QtCore.Signal(object)  # PIL.Image.Image
    status_changed = QtCore.Signal(str)
    error = QtCore.Signal(str)
    disconnected = QtCore.Signal()

    def __init__(
        self,
        backend: VncBackend | None = None,
        backend_name: BackendName = "vncdotool",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend if backend is not None else create_backend(backend_name)
        self._command_queue: queue.Queue[_Command] = queue.Queue()
        self._fps = 1
        self._connected = False

    def set_backend(self, backend: VncBackend) -> None:
        """Replace the backend. Must be called before connect()."""
        if self._connected:
            raise RuntimeError("Cannot change backend while connected")
        self._backend = backend

    def connect_to(self, host: str, port: int, password: str | None = None) -> None:
        self._command_queue.put(_ConnectCommand(host, port, password))

    def disconnect_from(self) -> None:
        self._command_queue.put(_DisconnectCommand())

    def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        self._command_queue.put(_KeyCommand(key, modifiers))

    def send_text(self, text: str) -> None:
        self._command_queue.put(_TextCommand(text))

    def send_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        self._command_queue.put(_PointerCommand(x, y, button_mask))

    def set_fps(self, fps: int) -> None:
        self._command_queue.put(_SetFpsCommand(fps))

    def _set_status(self, status: str) -> None:
        logger.debug("status %s", status)
        self.status_changed.emit(status)

    def _set_error(self, message: str) -> None:
        logger.warning("error %s", message)
        self.error.emit(message)

    def _handle_command(self, cmd: _Command) -> None:
        if isinstance(cmd, _ConnectCommand):
            self._do_connect(cmd.host, cmd.port, cmd.password)
        elif isinstance(cmd, _DisconnectCommand):
            self._do_disconnect()
        elif isinstance(cmd, _KeyCommand):
            if self._connected:
                self._backend.send_key(cmd.key, cmd.modifiers)
        elif isinstance(cmd, _TextCommand):
            if self._connected:
                self._backend.send_text(cmd.text)
        elif isinstance(cmd, _PointerCommand):
            if self._connected:
                self._backend.send_pointer_event(cmd.x, cmd.y, cmd.button_mask)
        elif isinstance(cmd, _SetFpsCommand):
            self._fps = max(1, min(30, cmd.fps))

    def _do_connect(self, host: str, port: int, password: str | None) -> None:
        self._set_status("connecting")
        try:
            self._backend.connect(host, port, password=password)
            self._connected = True
            self._set_status("connected")
            logger.info("Connected to %s:%d", host, port)
        except PasswordRequiredError:
            self._set_error("Server requires a password. Please enter the VNC password.")
            self._set_status("disconnected")
        except AuthError as exc:
            self._set_error(f"Authentication failed: {exc}")
            self._set_status("disconnected")
        except ConnectionRefusedError:
            self._set_error(f"Connection refused to {host}:{port}")
            self._set_status("disconnected")
        except TimeoutError:
            self._set_error(f"Connection to {host}:{port} timed out")
            self._set_status("disconnected")
        except Exception as exc:
            self._set_error(f"Could not connect: {exc}")
            self._set_status("disconnected")

    def _do_disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        try:
            self._backend.disconnect()
        except Exception as exc:
            logger.debug("disconnect error %s", exc)
        self._set_status("disconnected")
        self.disconnected.emit()

    def _fetch_frame(self) -> None:
        try:
            if not self._backend.is_connected:
                self._do_disconnect()
                return
            frame = self._backend.get_frame()
            if frame is not None:
                self.frame_ready.emit(frame)
        except Exception as exc:
            logger.warning("Frame fetch failed: %s", exc)
            self._do_disconnect()
            self._set_error(f"Lost connection: {exc}")

    def run(self) -> None:
        self._set_status("disconnected")
        last_frame = 0.0
        while not self.isInterruptionRequested():
            # Drain commands continuously so input is never stuck behind the
            # frame interval; only wait up to 50ms for the next command.
            try:
                cmd = self._command_queue.get(timeout=0.05)
                self._handle_command(cmd)
                continue
            except queue.Empty:
                pass

            if self._connected:
                now = time.monotonic()
                if now - last_frame >= 1.0 / self._fps:
                    self._fetch_frame()
                    last_frame = now

        # Clean up on thread exit.
        self._do_disconnect()

    def shutdown(self) -> None:
        """Request a clean shutdown and wait for the thread to finish."""
        self.requestInterruption()
        self.wait(5000)
