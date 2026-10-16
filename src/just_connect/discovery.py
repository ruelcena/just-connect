"""LAN server discovery with one-time style connect codes.

Instead of typing a host/IP, the person sharing their desktop reads out a
short generated code (e.g. ``ABCD-EFGH``) shown by ``just-connect-server``.
The person connecting types the code, and the client finds the matching
server on the local network automatically.

Security properties:

- Codes are generated with :mod:`secrets` (8 chars from a 32-char
  unambiguous alphabet, ~40 bits of entropy).
- The code is **never broadcast**. Announcements carry a random per-message
  nonce and ``HMAC-SHA256(code, nonce)``; the client recomputes the tag with
  the code it was given and compares in constant time. A passive listener
  learns nothing reusable, and a captured announcement cannot be replayed to
  impersonate the server.
- The built-in server uses the code as its VNC password by default, so only
  someone who was given the code can actually authenticate.

Discovery uses UDP broadcast, so it works within the same LAN segment. Over
the internet, tunnel with SSH/VPN and connect manually as before.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import socket
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 45999
BROADCAST_ADDR = "255.255.255.255"
_PROTOCOL = "just-connect"
_VERSION = 1

# Unambiguous alphabet: no 0/O, 1/I/L.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
_TAG_BYTES = 16


def generate_code() -> str:
    """Return a new random connect code formatted ``XXXX-XXXX``."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(text: str) -> str:
    """Strip separators and case so ``abcd-efgh`` matches ``ABCD-EFGH``."""
    return "".join(ch for ch in text.upper() if ch in _ALPHABET)


def is_valid_code(text: str) -> bool:
    return len(normalize_code(text)) == CODE_LENGTH


def _compute_tag(code: str, nonce: bytes) -> bytes:
    key = normalize_code(code).encode("utf-8")
    return hmac.new(key, nonce, hashlib.sha256).digest()[:_TAG_BYTES]


@dataclass
class ServerInfo:
    """A server discovered on the local network."""

    host: str
    port: int
    name: str


def build_announcement(code: str, server_port: int, name: str) -> bytes:
    """Build a signed announcement payload with a fresh random nonce."""
    nonce = secrets.token_bytes(16)
    payload = {
        "app": _PROTOCOL,
        "v": _VERSION,
        "port": server_port,
        "name": name,
        "nonce": nonce.hex(),
        "tag": _compute_tag(code, nonce).hex(),
    }
    return json.dumps(payload).encode("utf-8")


def parse_announcement(data: bytes, code: str, host: str) -> ServerInfo | None:
    """Validate an announcement against the given code.

    Returns a :class:`ServerInfo` only if the payload is a well-formed
    just-connect announcement whose tag matches the code; otherwise None.
    """
    try:
        payload = json.loads(data.decode("utf-8"))
        if payload.get("app") != _PROTOCOL or payload.get("v") != _VERSION:
            return None
        nonce = bytes.fromhex(payload["nonce"])
        tag = bytes.fromhex(payload["tag"])
        port = int(payload["port"])
        name = str(payload.get("name") or host)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    if not (1 <= port <= 65535):
        return None
    if not hmac.compare_digest(tag, _compute_tag(code, nonce)):
        return None
    return ServerInfo(host=host, port=port, name=name)


class DiscoveryAnnouncer:
    """Broadcasts a signed announcement for a server until stopped."""

    def __init__(
        self,
        code: str,
        server_port: int,
        name: str | None = None,
        discovery_port: int = DISCOVERY_PORT,
        broadcast_addr: str = BROADCAST_ADDR,
        interval: float = 2.0,
    ) -> None:
        self._code = code
        self._server_port = server_port
        self._name = name or socket.gethostname()
        self._discovery_port = discovery_port
        self._broadcast_addr = broadcast_addr
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError as exc:
            logger.warning("Discovery announcer disabled: %s", exc)
            return
        try:
            while not self._stop.is_set():
                message = build_announcement(self._code, self._server_port, self._name)
                try:
                    sock.sendto(message, (self._broadcast_addr, self._discovery_port))
                except OSError as exc:
                    logger.warning("Discovery broadcast failed: %s", exc)
                self._stop.wait(self._interval)
        finally:
            sock.close()


def find_server(
    code: str,
    timeout: float = 6.0,
    discovery_port: int = DISCOVERY_PORT,
) -> ServerInfo | None:
    """Listen for a server announcement matching *code*.

    Returns the first matching :class:`ServerInfo`, or None if no matching
    server announced itself before *timeout* seconds elapsed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):  # not on Windows
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", discovery_port))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            sock.settimeout(remaining)
            try:
                data, (host, _) = sock.recvfrom(2048)
            except socket.timeout:
                return None
            info = parse_announcement(data, code, host)
            if info is not None:
                logger.info(
                    "Discovered server %r at %s:%d", info.name, info.host, info.port
                )
                return info
    finally:
        sock.close()
