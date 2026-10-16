"""Tests for vncdotool backend helpers."""

from __future__ import annotations

import pytest

from just_connect.vncdotool_backend import (
    _translate_typed_char,
    _vncdotool_key,
)


@pytest.mark.parametrize(
    "key, modifiers, expected",
    [
        ("a", None, "a"),
        ("a", [], "a"),
        ("a", ["ctrl"], "ctrl-a"),
        ("c", ["ctrl", "shift"], "ctrl-shift-c"),
        ("Enter", None, "return"),
        ("ENTER", ["ctrl"], "ctrl-return"),
        ("esc", None, "esc"),
        ("Escape", None, "esc"),
        ("left", ["alt"], "alt-left"),
        ("F1", None, "f1"),
    ],
)
def test_vncdotool_key(key, modifiers, expected) -> None:
    assert _vncdotool_key(key, modifiers) == expected


@pytest.mark.parametrize(
    "char, expected",
    [
        ("a", "a"),
        ("\n", "return"),
        ("\r", "return"),
        ("\t", "tab"),
        (" ", "space"),
        ("-", "minus"),
    ],
)
def test_translate_typed_char(char, expected) -> None:
    assert _translate_typed_char(char) == expected
