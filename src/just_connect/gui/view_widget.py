"""Widget that displays the remote screen and forwards input events."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class ViewWidget(QtWidgets.QLabel):
    """Displays the remote framebuffer and forwards keyboard/mouse input."""

    key_pressed = QtCore.Signal(str, list)  # key, modifiers
    pointer_event = QtCore.Signal(int, int, int)  # x, y, button_mask

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Not connected")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._scale_factor = 1.0
        self._image_offset = QtCore.QPoint(0, 0)
        self._last_button_mask = 0

    def set_frame(self, pixmap: QtGui.QPixmap) -> None:
        """Update the displayed frame, scaling to fit while preserving aspect."""
        if pixmap.isNull():
            return
        available = self.size()
        scaled = pixmap.scaled(
            available,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self._scale_factor = scaled.width() / max(1, pixmap.width())
        self._image_offset = QtCore.QPoint(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
        )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = self._qt_key_to_name(event)
        if key is None:
            super().keyPressEvent(event)
            return
        modifiers = self._active_modifiers(event.modifiers())
        self.key_pressed.emit(key, modifiers)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        # We only forward press events; vncdotool sends press+release itself.
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._last_button_mask = self._button_mask_from_event(event)
        self._emit_pointer_event(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._last_button_mask = 0
        self._emit_pointer_event(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._emit_pointer_event(event)

    def _emit_pointer_event(self, event: QtGui.QMouseEvent) -> None:
        x, y = self._widget_to_remote(event.pos())
        self.pointer_event.emit(x, y, self._last_button_mask)

    def _widget_to_remote(self, pos: QtCore.QPoint) -> tuple[int, int]:
        local = pos - self._image_offset
        x = int(local.x() / self._scale_factor) if self._scale_factor else 0
        y = int(local.y() / self._scale_factor) if self._scale_factor else 0
        # Clamp to non-negative values; the backend can clamp to screen size.
        return max(0, x), max(0, y)

    def _button_mask_from_event(self, event: QtGui.QMouseEvent) -> int:
        button = event.button()
        if button == QtCore.Qt.MouseButton.LeftButton:
            return 1
        if button == QtCore.Qt.MouseButton.MiddleButton:
            return 2
        if button == QtCore.Qt.MouseButton.RightButton:
            return 4
        return 0

    def _active_modifiers(self, mods: QtCore.Qt.KeyboardModifier) -> list[str]:
        result: list[str] = []
        if mods & QtCore.Qt.KeyboardModifier.ShiftModifier:
            result.append("shift")
        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            result.append("ctrl")
        if mods & QtCore.Qt.KeyboardModifier.AltModifier:
            result.append("alt")
        if mods & QtCore.Qt.KeyboardModifier.MetaModifier:
            result.append("meta")
        return result

    def _qt_key_to_name(self, event: QtGui.QKeyEvent) -> str | None:
        key = event.key()
        # Let typed characters through as-is when no complex modifier is used.
        text = event.text()
        if text and text.isprintable() and key not in self._special_keys():
            return text

        special = self._special_key_map()
        if key in special:
            return special[key]
        return None

    @staticmethod
    def _special_keys() -> set[int]:
        return {
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Backspace,
            QtCore.Qt.Key.Key_Tab,
            QtCore.Qt.Key.Key_Escape,
            QtCore.Qt.Key.Key_Delete,
            QtCore.Qt.Key.Key_Space,
        }

    @staticmethod
    def _special_key_map() -> dict[int, str]:
        return {
            QtCore.Qt.Key.Key_Return: "return",
            QtCore.Qt.Key.Key_Enter: "return",
            QtCore.Qt.Key.Key_Backspace: "backspace",
            QtCore.Qt.Key.Key_Tab: "tab",
            QtCore.Qt.Key.Key_Escape: "esc",
            QtCore.Qt.Key.Key_Delete: "delete",
            QtCore.Qt.Key.Key_Insert: "insert",
            QtCore.Qt.Key.Key_Home: "home",
            QtCore.Qt.Key.Key_End: "end",
            QtCore.Qt.Key.Key_PageUp: "pageup",
            QtCore.Qt.Key.Key_PageDown: "pagedown",
            QtCore.Qt.Key.Key_Left: "left",
            QtCore.Qt.Key.Key_Right: "right",
            QtCore.Qt.Key.Key_Up: "up",
            QtCore.Qt.Key.Key_Down: "down",
            QtCore.Qt.Key.Key_Space: "space",
            QtCore.Qt.Key.Key_F1: "f1",
            QtCore.Qt.Key.Key_F2: "f2",
            QtCore.Qt.Key.Key_F3: "f3",
            QtCore.Qt.Key.Key_F4: "f4",
            QtCore.Qt.Key.Key_F5: "f5",
            QtCore.Qt.Key.Key_F6: "f6",
            QtCore.Qt.Key.Key_F7: "f7",
            QtCore.Qt.Key.Key_F8: "f8",
            QtCore.Qt.Key.Key_F9: "f9",
            QtCore.Qt.Key.Key_F10: "f10",
            QtCore.Qt.Key.Key_F11: "f11",
            QtCore.Qt.Key.Key_F12: "f12",
        }
