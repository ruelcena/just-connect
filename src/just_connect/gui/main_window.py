"""Main application window."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import ImageQt
from PySide6 import QtCore, QtGui, QtWidgets

from just_connect.config import AppConfig, load_config, save_config
from just_connect.keyring_store import (
    delete_password,
    get_password,
    set_password,
)
from just_connect.worker import VncWorker

from .connect_dialog import ConnectDialog
from .view_widget import ViewWidget

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    """Primary window: remote view, status, controls, screenshot."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("just-connect")
        self.resize(960, 720)

        self._config = load_config()
        self._current_password: str | None = None

        self._worker = VncWorker(backend_name=self._config.backend)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.error.connect(self._on_error)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.start()

        self._setup_ui()
        self._apply_status("disconnected")

    def _setup_ui(self) -> None:
        toolbar = QtWidgets.QToolBar()
        self.addToolBar(toolbar)

        self._connect_action = toolbar.addAction("Connect")
        self._connect_action.triggered.connect(self._open_connect_dialog)

        self._disconnect_action = toolbar.addAction("Disconnect")
        self._disconnect_action.triggered.connect(self._disconnect)
        self._disconnect_action.setEnabled(False)

        toolbar.addSeparator()

        self._screenshot_action = toolbar.addAction("Screenshot")
        self._screenshot_action.triggered.connect(self._save_screenshot)
        self._screenshot_action.setEnabled(False)

        toolbar.addSeparator()

        toolbar.addWidget(QtWidgets.QLabel("FPS:"))
        self._fps_spin = QtWidgets.QSpinBox()
        self._fps_spin.setRange(1, 10)
        self._fps_spin.setValue(self._config.fps)
        self._fps_spin.valueChanged.connect(self._worker.set_fps)
        toolbar.addWidget(self._fps_spin)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        self._view = ViewWidget()
        self._view.key_pressed.connect(self._worker.send_key)
        self._view.pointer_event.connect(self._worker.send_pointer_event)
        layout.addWidget(self._view, stretch=1)

        bottom = QtWidgets.QHBoxLayout()
        self._status_label = QtWidgets.QLabel("Disconnected")
        bottom.addWidget(self._status_label)

        bottom.addStretch()

        self._text_edit = QtWidgets.QLineEdit()
        self._text_edit.setPlaceholderText("Type text to send...")
        self._text_edit.returnPressed.connect(self._send_text)
        bottom.addWidget(self._text_edit, stretch=1)

        send_button = QtWidgets.QPushButton("Send text")
        send_button.clicked.connect(self._send_text)
        bottom.addWidget(send_button)

        layout.addLayout(bottom)

    def _open_connect_dialog(self) -> None:
        dialog = ConnectDialog(self._config, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        host = dialog.host()
        port = dialog.port()
        password = dialog.password() or None

        if dialog.remember_password() and password:
            set_password(host, port, password)
        elif dialog.remember_password():
            delete_password(host, port)

        save_config(self._config)
        self._current_password = password
        self._worker.connect_to(host, port, password)

    def _disconnect(self) -> None:
        self._worker.disconnect_from()

    def _send_text(self) -> None:
        text = self._text_edit.text()
        if text:
            self._worker.send_text(text)
            self._text_edit.clear()

    def _on_frame_ready(self, frame) -> None:
        try:
            qimage = ImageQt.ImageQt(frame)
            pixmap = QtGui.QPixmap.fromImage(qimage)
            self._view.set_frame(pixmap)
        except Exception as exc:
            logger.warning("Could not convert frame: %s", exc)

    def _on_status_changed(self, status: str) -> None:
        self._apply_status(status)

    def _apply_status(self, status: str) -> None:
        self._status_label.setText(status.capitalize())
        connected = status == "connected"
        self._connect_action.setEnabled(not connected)
        self._disconnect_action.setEnabled(connected)
        self._screenshot_action.setEnabled(connected)
        if status == "disconnected":
            self._view.setText("Disconnected")

    def _on_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Connection error", message)

    def _on_disconnected(self) -> None:
        self._view.setText("Disconnected")

    def _save_screenshot(self) -> None:
        pixmap = self._view.pixmap()
        if pixmap is None or pixmap.isNull():
            QtWidgets.QMessageBox.warning(
                self, "No frame", "There is no frame to save yet."
            )
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Screenshot",
            str(Path.home() / "screenshot.png"),
            "PNG Images (*.png)",
        )
        if path:
            pixmap.save(path, "PNG")
            logger.info("Saved screenshot to %s", path)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._worker.shutdown()
        super().closeEvent(event)
