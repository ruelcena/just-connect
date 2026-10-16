"""Shared test fixtures."""

from __future__ import annotations

import pytest

from just_connect.backend import VncBackend


class MockBackend(VncBackend):
    """In-memory backend for testing the VncBackend interface."""

    def __init__(self) -> None:
        self.host: str | None = None
        self.port: int | None = None
        self.password: str | None = None
        self.connected = False
        self.frames: list = []
        self.keys: list[tuple[str, list[str] | None]] = []
        self.texts: list[str] = []
        self.pointer_events: list[tuple[int, int, int]] = []

    def connect(
        self,
        host: str,
        port: int,
        password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if host == "refused":
            raise ConnectionRefusedError("connection refused")
        if host == "timeout":
            raise TimeoutError("connection timed out")
        if host == "needpass":
            from just_connect.backend import PasswordRequiredError

            raise PasswordRequiredError("password required")
        if host == "badpass":
            from just_connect.backend import AuthError

            raise AuthError("authentication failed")
        self.host = host
        self.port = port
        self.password = password
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    def get_frame(self):
        from PIL import Image

        if not self.connected:
            return None
        if not self.frames:
            return Image.new("RGB", (640, 480), color="black")
        return self.frames[-1]

    def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        self.keys.append((key, modifiers))

    def send_text(self, text: str) -> None:
        self.texts.append(text)

    def send_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        self.pointer_events.append((x, y, button_mask))


@pytest.fixture
def mock_backend() -> MockBackend:
    return MockBackend()
