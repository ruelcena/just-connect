"""Minimal in-memory VNC server for tests and manual verification.

Supports RFB 3.8, None and VNC-password auth, and RAW RGB32 encoding. It does
not serve a real desktop; it renders a small checkerboard that changes color
when keys are pressed.
"""

from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass
from typing import Callable




@dataclass
class _PixelFormat:
    bpp: int = 32
    depth: int = 24
    big_endian: bool = False
    true_color: bool = True
    red_max: int = 255
    green_max: int = 255
    blue_max: int = 255
    red_shift: int = 0
    green_shift: int = 8
    blue_shift: int = 16

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


class MiniVncServer:
    """A tiny VNC server that runs in a background thread."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        password: str | None = None,
        width: int = 320,
        height: int = 240,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.width = width
        self.height = height
        self.keys_received: list[tuple[bool, int]] = []
        self.pointer_events: list[tuple[int, int, int]] = []
        self._frame_counter = 0
        self._sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> int:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._shutdown.set()
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2)

    def _serve(self) -> None:
        try:
            self._conn, _ = self._sock.accept()
        except OSError:
            return
        try:
            self._handshake()
            self._main_loop()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self._conn.close()

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._conn.recv(n - len(data))
            if not chunk:
                raise ConnectionResetError("client closed connection")
            data += chunk
        return data

    def _send(self, data: bytes) -> None:
        self._conn.sendall(data)

    def _handshake(self) -> None:
        print("handshake: sending version", flush=True)
        self._send(b"RFB 003.008\n")
        version = self._recv_exact(12)
        print(f"handshake: got version {version!r}", flush=True)
        if not version.startswith(b"RFB 003."):
            raise ValueError(f"unsupported version: {version}")

        if self.password:
            self._send(b"\x02\x01\x02")  # 2 security types: None, VNC auth
        else:
            self._send(b"\x01\x01")  # 1 security type: None

        selected = self._recv_exact(1)[0]
        print(f"handshake: selected security {selected}", flush=True)
        if selected == 1:
            self._send(struct.pack("!I", 0))  # OK
        elif selected == 2:
            self._do_vnc_auth()
        else:
            raise ValueError(f"unsupported security type: {selected}")

        shared = self._recv_exact(1)
        print(f"handshake: shared flag {shared!r}", flush=True)
        # Server init
        pf = _PixelFormat()
        name = b"mini-vnc"
        init = (
            struct.pack("!HH", self.width, self.height)
            + pf.pack()
            + struct.pack("!I", len(name))
            + name
        )
        print(f"handshake: sending server init {len(init)} bytes", flush=True)
        self._send(init)

    def _do_vnc_auth(self) -> None:
        from vncdotool.rfb import _vnc_des, des_encrypt

        challenge = b"\x01\x02\x03\x04\x05\x06\x07\x08" * 2
        self._send(challenge)
        response = self._recv_exact(16)
        expected = des_encrypt(_vnc_des(self.password), challenge)
        if response == expected:
            self._send(struct.pack("!I", 0))
        else:
            self._send(struct.pack("!I", 1))
            raise ValueError("authentication failed")

    def _main_loop(self) -> None:
        print("main_loop: started", flush=True)
        while not self._shutdown.is_set():
            msg_type = self._recv_exact(1)[0]
            print(f"main_loop: msg_type={msg_type}", flush=True)
            if msg_type == 0:  # SetPixelFormat
                self._recv_exact(19)
            elif msg_type == 2:  # SetEncodings
                count = struct.unpack("!H", self._recv_exact(3)[1:])[0]
                self._recv_exact(count * 4)
            elif msg_type == 3:  # FramebufferUpdateRequest
                incremental = self._recv_exact(1)[0]
                x, y, w, h = struct.unpack("!HHHH", self._recv_exact(8))
                print(f"main_loop: FUR incremental={incremental} {x},{y} {w}x{h}", flush=True)
                self._send_framebuffer_update(x, y, w, h)
            elif msg_type == 4:  # KeyEvent
                down, key = struct.unpack("!BxxI", self._recv_exact(7))
                with self._lock:
                    self.keys_received.append((bool(down), key))
            elif msg_type == 5:  # PointerEvent
                button_mask, x, y = struct.unpack("!BHH", self._recv_exact(5))
                with self._lock:
                    self.pointer_events.append((button_mask, x, y))
            elif msg_type == 6:  # ClientCutText
                length = struct.unpack("!I", self._recv_exact(7)[3:])[0]
                self._recv_exact(length)

    def _render_pixel(self, px: int, py: int) -> bytes:
        with self._lock:
            counter = self._frame_counter
        # Simple animated gradient so tests can see updates.
        r = (px * 255 // max(1, self.width - 1) + counter) % 256
        g = (py * 255 // max(1, self.height - 1) + counter * 2) % 256
        b = (128 + counter * 3) % 256
        return bytes([r, g, b, 0])

    def _send_framebuffer_update(self, x: int, y: int, w: int, h: int) -> None:
        with self._lock:
            self._frame_counter += 1
        rect_header = struct.pack("!HHHHi", x, y, w, h, 0)  # encoding 0 = RAW
        update_header = struct.pack("!BxH", 0, 1)
        pixels = b"".join(
            self._render_pixel(px, py)
            for py in range(y, y + h)
            for px in range(x, x + w)
        )
        self._send(update_header + rect_header + pixels)


if __name__ == "__main__":
    import time

    srv = MiniVncServer(port=5900, password="secret")
    port = srv.start()
    print(f"Mini VNC server listening on port {port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
