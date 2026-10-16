"""Abstract VNC backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


class VncError(Exception):
    """Base exception for VNC backend errors."""


class AuthError(VncError):
    """Authentication failed or was rejected by the server."""


class PasswordRequiredError(AuthError):
    """The server requires a password but none was supplied."""


class VncBackend(ABC):
    """Abstract interface for a VNC client backend.

    Implementations must be callable from a single worker thread. They do not
    need to be thread-safe across multiple threads, but they must never block
    the UI thread.
    """

    @abstractmethod
    def connect(
        self,
        host: str,
        port: int,
        password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Connect to a VNC server.

        Raises:
            ConnectionRefusedError: if the TCP connection is refused.
            TimeoutError: if the connection times out.
            PasswordRequiredError: if the server requires a password and none
                was provided.
            AuthError: if authentication fails.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the server and release resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if currently connected."""

    @abstractmethod
    def get_frame(self) -> "Image | None":
        """Return the most recent remote framebuffer as a PIL Image.

        Implementations may trigger a refresh internally. Returns None if no
        frame has been received yet.
        """

    @abstractmethod
    def send_key(self, key: str, modifiers: list[str] | None = None) -> None:
        """Send a single key press (optionally with modifiers).

        ``key`` is a logical key name such as "a", "enter", "f1", "left".
        ``modifiers`` is a list of modifier names such as "shift", "ctrl",
        "alt", "meta".
        """

    @abstractmethod
    def send_text(self, text: str) -> None:
        """Type a string of text on the remote host."""

    @abstractmethod
    def send_pointer_event(self, x: int, y: int, button_mask: int) -> None:
        """Send a mouse/pointer event.

        ``button_mask`` follows the VNC convention: bit 0 = left, 1 = middle,
        2 = right, etc.
        """
