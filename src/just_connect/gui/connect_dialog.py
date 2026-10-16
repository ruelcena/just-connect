"""Connection dialog: connect code with auto-discovery, or manual host/port.

No username field. The default tab takes the connect code shown by
``just-connect-server`` and finds the matching server on the local network;
the manual tab keeps the classic host/IP + port form as a fallback.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from just_connect.config import AppConfig
from just_connect.discovery import (
    ServerInfo,
    find_server,
    is_valid_code,
    normalize_code,
)


class _DiscoveryThread(QtCore.QThread):
    """Runs LAN discovery off the UI thread."""

    found = QtCore.Signal(object)  # ServerInfo
    not_found = QtCore.Signal()

    def __init__(self, code: str, timeout: float = 8.0, parent=None) -> None:
        super().__init__(parent)
        self._code = code
        self._timeout = timeout

    def run(self) -> None:
        info = find_server(self._code, timeout=self._timeout)
        if info is None:
            self.not_found.emit()
        else:
            self.found.emit(info)


class ConnectDialog(QtWidgets.QDialog):
    """Dialog to collect VNC connection details."""

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to VNC")
        self.setMinimumWidth(400)

        self._config = config
        self._resolved_host = ""
        self._resolved_port = config.port
        self._discovery: _DiscoveryThread | None = None

        layout = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_code_tab(), "Connect code")
        tabs.addTab(self._build_manual_tab(), "Manual (IP)")
        self._tabs = tabs

        self._status_label = QtWidgets.QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._code_edit.setFocus()

    def _build_code_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)

        self._code_edit = QtWidgets.QLineEdit()
        self._code_edit.setPlaceholderText("e.g. ABCD-EFGH")
        self._code_edit.setMaxLength(9)
        form.addRow("Connect code", self._code_edit)

        hint = QtWidgets.QLabel(
            "Enter the code shown on the remote computer by "
            "just-connect-server. The server is found on your network "
            "automatically — no IP address needed."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return tab

    def _build_manual_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)

        self._host_edit = QtWidgets.QLineEdit(self._config.host)
        self._host_edit.setPlaceholderText("hostname or IP")
        form.addRow("Host / IP", self._host_edit)

        self._port_spin = QtWidgets.QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(self._config.port)
        form.addRow("Port", self._port_spin)

        self._password_edit = QtWidgets.QLineEdit()
        self._password_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("leave blank for anonymous / no-auth")
        form.addRow("Password", self._password_edit)

        self._remember_password = QtWidgets.QCheckBox("Remember password in keyring")
        self._remember_password.setChecked(False)
        form.addRow(self._remember_password)

        warning = QtWidgets.QLabel(
            "Warning: VNC password auth and RAW encoding are sent unencrypted. "
            "Use an SSH tunnel or VPN when connecting over the internet."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: darkorange;")
        form.addRow(warning)
        return tab

    def host(self) -> str:
        return self._resolved_host

    def port(self) -> int:
        return self._resolved_port

    def password(self) -> str:
        if self._tabs.currentIndex() == 0:
            # The server uses the normalized (dash-less) code as its password.
            return normalize_code(self._code_edit.text())
        return self._password_edit.text()

    def remember_password(self) -> bool:
        return (
            self._tabs.currentIndex() == 1 and self._remember_password.isChecked()
        )

    def accept(self) -> None:
        if self._tabs.currentIndex() == 0:
            self._accept_with_code()
        else:
            self._accept_manual()

    def _accept_with_code(self) -> None:
        code = self._code_edit.text().strip()
        if not is_valid_code(code):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid code",
                "Please enter the 8-character connect code shown by the server.",
            )
            return
        self._set_busy(True, f"Looking for the server with code {code}...")
        self._discovery = _DiscoveryThread(code, parent=self)
        self._discovery.found.connect(self._on_server_found)
        self._discovery.not_found.connect(self._on_server_not_found)
        self._discovery.start()

    def _on_server_found(self, info: ServerInfo) -> None:
        self._set_busy(False, "")
        self._resolved_host = info.host
        self._resolved_port = info.port
        self._config.host = info.host
        self._config.port = info.port
        super().accept()

    def _on_server_not_found(self) -> None:
        self._set_busy(False, "")
        QtWidgets.QMessageBox.warning(
            self,
            "Server not found",
            "No server with that code answered on the local network.\n\n"
            "Check that just-connect-server is running on the remote computer, "
            "that both machines are on the same network, and that the code is "
            "correct. Firewalls can also block discovery.",
        )

    def _set_busy(self, busy: bool, message: str) -> None:
        self._buttons.setEnabled(not busy)
        self._code_edit.setEnabled(not busy)
        self._status_label.setText(message)

    def _accept_manual(self) -> None:
        if not self._host_edit.text().strip():
            QtWidgets.QMessageBox.warning(
                self, "Missing host", "Please enter a host or IP address."
            )
            return
        self._resolved_host = self._host_edit.text().strip()
        self._resolved_port = self._port_spin.value()
        # Persist host/port for next time.
        self._config.host = self._resolved_host
        self._config.port = self._resolved_port
        super().accept()

    def reject(self) -> None:
        if self._discovery is not None and self._discovery.isRunning():
            self._discovery.wait(500)
        super().reject()
