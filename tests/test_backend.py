"""Tests for the VncBackend abstract interface."""

from __future__ import annotations

import pytest
from PIL import Image

from just_connect.backend import (
    AuthError,
    PasswordRequiredError,
    VncBackend,
    VncError,
)


def test_cannot_instantiate_abstract_backend() -> None:
    with pytest.raises(TypeError):
        VncBackend()  # type: ignore[abstract]


def test_backend_exceptions_inherit_from_base() -> None:
    assert issubclass(AuthError, VncError)
    assert issubclass(PasswordRequiredError, AuthError)


def test_mock_backend_connect_and_disconnect(mock_backend) -> None:
    assert not mock_backend.is_connected
    mock_backend.connect("127.0.0.1", 5900)
    assert mock_backend.is_connected
    assert mock_backend.host == "127.0.0.1"
    assert mock_backend.port == 5900
    mock_backend.disconnect()
    assert not mock_backend.is_connected


def test_mock_backend_get_frame(mock_backend) -> None:
    mock_backend.connect("127.0.0.1", 5900)
    frame = mock_backend.get_frame()
    assert isinstance(frame, Image.Image)
    assert frame.size == (640, 480)


def test_mock_backend_send_key(mock_backend) -> None:
    mock_backend.connect("127.0.0.1", 5900)
    mock_backend.send_key("a", ["ctrl"])
    assert mock_backend.keys == [("a", ["ctrl"])]


def test_mock_backend_send_text(mock_backend) -> None:
    mock_backend.connect("127.0.0.1", 5900)
    mock_backend.send_text("hello")
    assert mock_backend.texts == ["hello"]


def test_mock_backend_send_pointer_event(mock_backend) -> None:
    mock_backend.connect("127.0.0.1", 5900)
    mock_backend.send_pointer_event(10, 20, 1)
    assert mock_backend.pointer_events == [(10, 20, 1)]


def test_mock_backend_connection_refused(mock_backend) -> None:
    with pytest.raises(ConnectionRefusedError):
        mock_backend.connect("refused", 5900)


def test_mock_backend_timeout(mock_backend) -> None:
    with pytest.raises(TimeoutError):
        mock_backend.connect("timeout", 5900)


def test_mock_backend_password_required(mock_backend) -> None:
    with pytest.raises(PasswordRequiredError):
        mock_backend.connect("needpass", 5900)


def test_mock_backend_auth_failed(mock_backend) -> None:
    with pytest.raises(AuthError):
        mock_backend.connect("badpass", 5900)
