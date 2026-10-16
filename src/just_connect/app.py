"""GUI application entry point."""

from __future__ import annotations

import sys

from PySide6 import QtWidgets

from .logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    app = QtWidgets.QApplication(argv or sys.argv)
    app.setApplicationName("just-connect")
    app.setOrganizationName("just-connect")

    from .gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
