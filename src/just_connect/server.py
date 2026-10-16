"""Minimal Python VNC server for just-connect.

This lets you share the local desktop without installing a third-party VNC
server such as TightVNC or TigerVNC. Run it on the computer you want to
control:

    python -m just_connect.server --host 0.0.0.0 --port 5900

By default the server generates a random connect code, uses it as the VNC
password, and announces itself on the local network so clients can connect
by entering the code instead of an IP address. Anonymous / no-auth
connections are still available with ``--no-auth``. Mouse and keyboard input
are injected with pyautogui.
"""

from __future__ import annotations

import argparse
import logging
import select
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

from PIL import Image
from PIL import ImageGrab

from .logging_config import configure_logging
from .discovery import DiscoveryAnnouncer, generate_code, normalize_code

try:
    import mss
except ImportError:  # pragma: no cover
    mss = None

try:
    import pyautogui

    # Remote input must be low-latency: no artificial per-call delay, and no
    # corner-slam abort (a remote user dragging to a corner would kill input).
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False
except ImportError:  # pragma: no cover
    pyautogui = None

try:
    from vncdotool.rfb import _vnc_des, des_encrypt
except ImportError:  # pragma: no cover
    raise ImportError("vncdotool is required for the built-in server.")

logger = logging.getLogger(__name__)

# VNC keysym -> pyautogui key name
_KEYSYM_TO_PYAUTO = {
    0xFF08: "backspace",
    0xFF09: "tab",
    0xFF0D: "return",
    0xFF1B: "esc",
    0xFF20: "space",
    0xFF50: "home",
    0xFF51: "left",
    0xFF52: "up",
    0xFF53: "right",
    0xFF54: "down",
    0xFF55: "pageup",
    0xFF56: "pagedown",
    0xFF57: "end",
    0xFF63: "insert",
    0xFFFF: "delete",
    0xFFBE: "f1",
    0xFFBF: "f2",
    0xFFC0: "f3",
    0xFFC1: "f4",
    0xFFC2: "f5",
    0xFFC3: "f6",
    0xFFC4: "f7",
    0xFFC5: "f8",
    0xFFC6: "f9",
    0xFFC7: "f10",
    0xFFC8: "f11",
    0xFFC9: "f12",
}

_MODIFIER_KEYSYMS = {
    0xFFE1: "shift",  # Shift_L
    0xFFE2: "shift",  # Shift_R
    0xFFE3: "ctrl",   # Control_L
    0xFFE4: "ctrl",   # Control_R
    0xFFE9: "alt",    # Alt_L
    0xFFEA: "alt",    # Alt_R
    0xFFEB: "win",    # Meta_L
    0xFFEC: "win",    # Meta_R
}


def _capture_screen() -> Image.Image:
    """Capture the primary monitor as a PIL RGB image."""
    if mss is not None:
        try:
            with mss.MSS() as sct:
                monitor = sct.monitors[1]  # primary monitor
                img = sct.grab(monitor)
                return Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
        except Exception as exc:
            logger.warning("mss capture failed (%s), falling back to ImageGrab", exc)
    # Fallback to PIL ImageGrab (Windows / macOS).
    return ImageGrab.grab().convert("RGB")


def _resize_to_fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """Downscale the image if it exceeds the requested size."""
    if image.width <= max_width and image.height <= max_height:
        return image
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return image


class _PixelFormat:
    bpp = 32
    depth = 24
    big_endian = False
    true_color = True
    red_max = 255
    green_max = 255
    blue_max = 255
    red_shift = 0
    green_shift = 8
    blue_shift = 16

    def pack(self) -> bytes:
        return struct.pack(
            "!BBB?HHHBBBxxx",
            self.bpp,
            self.depth,
            int(self.big_endian),
            self.true_color,
            self.red_max,
            self.green_max,
            self.blue_max,
            self.red_shift,
            self.green_shift,
            self.blue_shift,
        )


class VncServer:
    """A tiny VNC server that shares the local screen."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5900,
        password: str | None = None,
        max_width: int = 1920,
        max_height: int = 1080,
        fps: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.max_width = max_width
        self.max_height = max_height
        self.fps = fps

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._capture_thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._clients: list[_ClientHandler] = []
        self._lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._latest_frame: Image.Image | None = None

    def start(self) -> int:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(5)
        actual_port = self._sock.getsockname()[1]
        logger.info("VNC server listening on %s:%d", self.host, actual_port)
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return actual_port

    def stop(self) -> None:
        self._shutdown.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        with self._lock:
            for client in self._clients:
                client.close()
        if self._thread:
            self._thread.join(timeout=2)

    def get_latest_frame(self) -> Image.Image | None:
        """Return the most recently captured desktop frame (never blocks)."""
        with self._frame_lock:
            return self._latest_frame

    def _capture_loop(self) -> None:
        """Continuously capture the desktop so client threads never wait on it."""
        interval = 1.0 / max(1, self.fps)
        while not self._shutdown.is_set():
            started = time.monotonic()
            try:
                img = _capture_screen()
                img = _resize_to_fit(img, self.max_width, self.max_height)
                with self._frame_lock:
                    self._latest_frame = img.convert("RGB")
            except Exception as exc:
                logger.warning("Screen capture failed: %s", exc)
                with self._frame_lock:
                    if self._latest_frame is None:
                        self._latest_frame = Image.new("RGB", (640, 480), color="black")
            elapsed = time.monotonic() - started
            self._shutdown.wait(max(0.05, interval - elapsed))

    def _accept_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                conn, addr = self._sock.accept()
            except OSError:
                return
            logger.info("Client connected from %s", addr)
            handler = _ClientHandler(
                conn,
                password=self.password,
                get_latest_frame=self.get_latest_frame,
            )
            with self._lock:
                self._clients.append(handler)
            threading.Thread(target=handler.run, daemon=True).start()


class _ClientHandler:
    def __init__(
        self,
        conn: socket.socket,
        password: str | None,
        get_latest_frame: Callable[[], Image.Image | None],
    ) -> None:
        self._conn = conn
        self._password = password
        self._get_latest_frame = get_latest_frame
        self._closed = False

        self._width = 0
        self._height = 0
        self._button_mask = 0
        self._pressed_modifiers: set[str] = set()
        self._recv_buffer = b""
        self._requested_rect: tuple[int, int, int, int] | None = None
        self._update_lock = threading.Lock()
        self._update_event = threading.Event()

    def close(self) -> None:
        self._closed = True
        self._update_event.set()  # wake the sender thread so it can exit
        try:
            self._conn.close()
        except Exception:
            pass

    def _recv_exact(self, n: int) -> bytes:
        while len(self._recv_buffer) < n:
            chunk = self._conn.recv(max(4096, n - len(self._recv_buffer)))
            if not chunk:
                raise ConnectionResetError("client closed connection")
            self._recv_buffer += chunk
        result = self._recv_buffer[:n]
        self._recv_buffer = self._recv_buffer[n:]
        return result

    def _send(self, data: bytes) -> None:
        self._conn.sendall(data)

    def run(self) -> None:
        try:
            self._handshake()
            sender = threading.Thread(target=self._send_loop, daemon=True)
            sender.start()
            self._main_loop()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception as exc:
            logger.warning("Client handler error: %s", exc)
        finally:
            self.close()

    def _handshake(self) -> None:
        self._send(b"RFB 003.008\n")
        version = self._recv_exact(12)
        if not version.startswith(b"RFB 003."):
            raise ValueError(f"unsupported version: {version}")

        if self._password:
            self._send(b"\x02\x01\x02")  # None and VNC auth
        else:
            self._send(b"\x01\x01")  # None only

        selected = self._recv_exact(1)[0]
        if selected == 1:
            self._send(struct.pack("!I", 0))
        elif selected == 2:
            self._do_vnc_auth()
        else:
            raise ValueError(f"unsupported security type: {selected}")

        self._recv_exact(1)  # shared flag
        frame = self._wait_for_frame()
        self._width, self._height = frame.size
        pf = _PixelFormat()
        name = b"just-connect-server"
        self._send(
            struct.pack("!HH", self._width, self._height)
            + pf.pack()
            + struct.pack("!I", len(name))
            + name
        )

    def _do_vnc_auth(self) -> None:
        challenge = b"\x01\x02\x03\x04\x05\x06\x07\x08" * 2
        self._send(challenge)
        response = self._recv_exact(16)
        expected = des_encrypt(_vnc_des(self._password), challenge)
        if response == expected:
            self._send(struct.pack("!I", 0))
        else:
            self._send(struct.pack("!I", 1))
            raise ValueError("authentication failed")

    def _wait_for_frame(self, timeout: float = 5.0) -> Image.Image:
        """Wait until the capture thread has produced its first frame."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._get_latest_frame()
            if frame is not None:
                return frame
            time.sleep(0.05)
        raise TimeoutError("no screen frame captured")

    def _main_loop(self) -> None:
        """Read client messages and apply keyboard/pointer input immediately.

        FramebufferUpdateRequests only record the requested rectangle; the
        sender thread does the actual encoding and sending, so multi-megabyte
        RAW frames can never delay input events.
        """
        while not self._closed:
            try:
                ready, _, _ = select.select([self._conn], [], [], 1.0)
            except OSError:
                return
            if self._closed:
                return
            if not ready:
                continue

            try:
                msg_type = self._recv_exact(1)[0]
            except (ConnectionResetError, OSError):
                return

            try:
                if msg_type == 0:  # SetPixelFormat
                    self._recv_exact(19)  # ignore, we always use the same format
                elif msg_type == 2:  # SetEncodings
                    data = self._recv_exact(3)
                    count = struct.unpack("!xH", data)[0]
                    self._recv_exact(4 * count)  # ignore encodings
                elif msg_type == 3:  # FramebufferUpdateRequest
                    data = self._recv_exact(9)
                    x, y, w, h = struct.unpack("!xHHHH", data)
                    with self._update_lock:
                        self._requested_rect = (x, y, w, h)
                    self._update_event.set()
                elif msg_type == 4:  # KeyEvent
                    data = self._recv_exact(7)
                    down, keysym = struct.unpack("!BxxI", data)
                    self._handle_key(bool(down), keysym)
                elif msg_type == 5:  # PointerEvent
                    data = self._recv_exact(5)
                    button_mask, x, y = struct.unpack("!BHH", data)
                    self._handle_pointer(button_mask, x, y)
                elif msg_type == 6:  # ClientCutText
                    data = self._recv_exact(7)
                    length = struct.unpack("!xxxI", data)[0]
                    self._recv_exact(length)
                else:
                    logger.warning("Unknown client message type: %d", msg_type)
            except (ConnectionResetError, BrokenPipeError, OSError):
                return
            except Exception as exc:
                logger.warning("Error handling message type %s: %s", msg_type, exc)
                return

    def _send_loop(self) -> None:
        """Send framebuffer updates in response to client requests.

        Only the most recently requested rectangle is ever queued; requests
        arriving while a frame is being sent are coalesced into one update,
        so frame traffic can never build up a backlog on slow links.
        """
        while not self._closed:
            self._update_event.wait(timeout=0.5)
            self._update_event.clear()
            if self._closed:
                return
            with self._update_lock:
                rect = self._requested_rect
                self._requested_rect = None
            if rect is None:
                continue
            try:
                self._send_framebuffer_update(*rect)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.close()
                return
            except Exception as exc:
                logger.warning("Failed to send framebuffer update: %s", exc)
                self.close()
                return

    def _send_framebuffer_update(self, x: int, y: int, w: int, h: int) -> None:
        frame = self._get_latest_frame()
        if frame is None:
            return

        # Clamp to the current frame's bounds (resolution may have changed).
        width, height = frame.size
        w = min(w, max(0, width - x))
        h = min(h, max(0, height - y))
        if w <= 0 or h <= 0:
            return

        region = frame.crop((x, y, x + w, y + h))
        # Convert to RGBX (32-bit) for RAW encoding.
        rgbx = region.convert("RGBX").tobytes()

        rect_header = struct.pack("!HHHHi", x, y, w, h, 0)
        update_header = struct.pack("!BxH", 0, 1)
        self._send(update_header + rect_header + rgbx)

    def _handle_key(self, down: bool, keysym: int) -> None:
        if pyautogui is None:
            return

        if keysym in _MODIFIER_KEYSYMS:
            mod = _MODIFIER_KEYSYMS[keysym]
            if down:
                self._pressed_modifiers.add(mod)
                pyautogui.keyDown(mod)
            else:
                self._pressed_modifiers.discard(mod)
                pyautogui.keyUp(mod)
            return

        key_name = _KEYSYM_TO_PYAUTO.get(keysym)
        if key_name:
            if down:
                pyautogui.keyDown(key_name)
            else:
                pyautogui.keyUp(key_name)
            return

        # Printable ASCII.
        if 0x20 <= keysym <= 0x7E:
            char = chr(keysym)
            if down:
                pyautogui.keyDown(char)
            else:
                pyautogui.keyUp(char)

    def _handle_pointer(self, button_mask: int, x: int, y: int) -> None:
        if pyautogui is None:
            return

        pyautogui.moveTo(x, y)

        changed = self._button_mask ^ button_mask
        for bit in range(3):
            btn = bit + 1
            mask = 1 << bit
            if changed & mask:
                if button_mask & mask:
                    pyautogui.mouseDown(button={1: "left", 2: "middle", 3: "right"}[btn])
                else:
                    pyautogui.mouseUp(button={1: "left", 2: "middle", 3: "right"}[btn])
        self._button_mask = button_mask


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Built-in VNC server for just-connect")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5900, help="Listen port (default 5900)")
    parser.add_argument(
        "--code",
        default=None,
        help="Connect code to announce and use as password; "
        "a random one is generated if omitted",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="VNC password; overrides the connect code for authentication",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Allow anonymous / no-auth connections (insecure, trusted LANs only)",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Do not announce this server on the local network",
    )
    parser.add_argument("--max-width", type=int, default=1920, help="Max capture width")
    parser.add_argument("--max-height", type=int, default=1080, help="Max capture height")
    parser.add_argument("--fps", type=int, default=10, help="Max capture FPS")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    code = normalize_code(args.code) if args.code else None
    if code is None and not args.no_discovery:
        code = generate_code().replace("-", "")

    if args.password:
        password: str | None = args.password
    elif args.no_auth:
        password = None
    else:
        # Secure by default: the connect code doubles as the VNC password.
        if code is None:
            code = generate_code().replace("-", "")
        password = code

    server = VncServer(
        host=args.host,
        port=args.port,
        password=password,
        max_width=args.max_width,
        max_height=args.max_height,
        fps=args.fps,
    )
    port = server.start()

    announcer: DiscoveryAnnouncer | None = None
    if code is not None and not args.no_discovery:
        announcer = DiscoveryAnnouncer(code, port)
        announcer.start()

    display_code = f"{code[:4]}-{code[4:]}" if code else None
    logger.info("just-connect-server running on port %d", port)
    if display_code:
        lines = [
            "=" * 46,
            f"  Connect code:  {display_code}",
            "  Share this code with the person connecting.",
            "  They do not need this machine's IP address.",
        ]
        if args.password:
            lines.append("  (Authentication uses your --password, not the code.)")
        lines.append("=" * 46)
        # flush: the code must appear even when stdout is redirected.
        print("\n".join(lines), flush=True)
    if password is None:
        logger.warning(
            "Anonymous / no-auth mode: anyone on the network can view and "
            "control this desktop"
        )
    logger.info("Press Ctrl+C to stop")

    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        if announcer is not None:
            announcer.stop()
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
