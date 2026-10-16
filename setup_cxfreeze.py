"""cx_Freeze installer builder for just-connect.

Usage:
    python setup_cxfreeze.py build
    python setup_cxfreeze.py bdist_msi

The MSI is written to dist/.
"""

from __future__ import annotations

from cx_Freeze import Executable, setup

build_exe_options = {
    "packages": [
        "just_connect",
        "PySide6",
        "vncdotool",
        "twisted",
        "PIL",
        "keyring",
        "pyautogui",
        "mss",
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "pydoc",
        "xmlrpc",
    ],
    "include_msvcr": True,
}

bdist_msi_options = {
    "add_to_path": False,
    "all_users": False,
    "upgrade_code": "{f3b8c123-4567-4890-abcd-ef1234567890}",
}

executables = [
    Executable(
        "app_entry.py",
        base="gui",
        target_name="just-connect.exe",
        shortcut_name="just-connect",
        shortcut_dir="StartMenuFolder",
    ),
    Executable(
        "cli_entry.py",
        base="console",
        target_name="just-connect-cli.exe",
    ),
    Executable(
        "server_entry.py",
        base="console",
        target_name="just-connect-server.exe",
        shortcut_name="just-connect-server",
        shortcut_dir="StartMenuFolder",
    ),
]

setup(
    name="just-connect",
    version="0.2.0",
    description="A minimal Python VNC desktop client",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
