"""GUI smoke / integration tests."""

from __future__ import annotations

import time

import pytest
from PySide6 import QtCore, QtWidgets

from just_connect.gui.main_window import MainWindow

from .vnc_server import MiniVncServer


@pytest.fixture
def vnc_server():
    srv = MiniVncServer(port=0, password="secret")
    port = srv.start()
    yield srv, port
    srv.stop()


def test_main_window_connects_and_receives_frame(qtbot, vnc_server) -> None:
    srv, port = vnc_server

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    qtbot.addWidget(window)

    window._worker.connect_to("127.0.0.1", port, "secret")

    qtbot.waitUntil(
        lambda: window._status_label.text().lower() == "connected",
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: window._view.pixmap() is not None
        and not window._view.pixmap().isNull(),
        timeout=3000,
    )

    window.close()
