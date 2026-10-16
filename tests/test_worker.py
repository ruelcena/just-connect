"""Tests for VncWorker using pytest-qt."""

from __future__ import annotations

from just_connect.worker import VncWorker


def test_worker_emits_status_and_frame(qtbot, mock_backend) -> None:
    worker = VncWorker(backend=mock_backend)
    statuses: list[str] = []
    frames: list = []
    worker.status_changed.connect(statuses.append)
    worker.frame_ready.connect(frames.append)

    worker.start()
    worker.connect_to("127.0.0.1", 5900)

    qtbot.waitUntil(lambda: "connected" in statuses, timeout=2000)
    qtbot.waitUntil(lambda: len(frames) >= 1, timeout=2000)

    worker.shutdown()
    assert mock_backend.is_connected is False


def test_worker_emits_error_on_refused(qtbot, mock_backend) -> None:
    worker = VncWorker(backend=mock_backend)
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.start()

    worker.connect_to("refused", 5900)

    qtbot.waitUntil(lambda: len(errors) == 1, timeout=2000)
    assert "refused" in errors[0].lower()

    worker.shutdown()


def test_worker_forwards_key_and_text(qtbot, mock_backend) -> None:
    worker = VncWorker(backend=mock_backend)
    statuses: list[str] = []
    worker.status_changed.connect(statuses.append)
    worker.start()

    worker.connect_to("127.0.0.1", 5900)
    qtbot.waitUntil(lambda: "connected" in statuses, timeout=2000)

    worker.send_key("a", ["ctrl"])
    worker.send_text("hello")

    qtbot.waitUntil(
        lambda: len(mock_backend.keys) == 1 and len(mock_backend.texts) == 1,
        timeout=2000,
    )

    assert mock_backend.keys == [("a", ["ctrl"])]
    assert mock_backend.texts == ["hello"]
    worker.shutdown()


def test_worker_forwards_pointer_event(qtbot, mock_backend) -> None:
    worker = VncWorker(backend=mock_backend)
    statuses: list[str] = []
    worker.status_changed.connect(statuses.append)
    worker.start()

    worker.connect_to("127.0.0.1", 5900)
    qtbot.waitUntil(lambda: "connected" in statuses, timeout=2000)

    worker.send_pointer_event(100, 200, 1)

    qtbot.waitUntil(lambda: len(mock_backend.pointer_events) == 1, timeout=2000)
    assert mock_backend.pointer_events == [(100, 200, 1)]
    worker.shutdown()
