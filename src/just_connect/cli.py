"""Command-line script for quick VNC capture and keystrokes.

Connects either by connect code (auto-discovering the server on the local
network) or by explicit host/port, saves one screenshot, and types text.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .discovery import find_server, normalize_code
from .logging_config import configure_logging
from .vncdotool_backend import VncdotoolBackend

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to a VNC server, capture a screenshot, and type text."
    )
    parser.add_argument(
        "--code",
        default=None,
        help="Connect code shown by just-connect-server; the server is found "
        "on the local network automatically",
    )
    parser.add_argument("--host", default=None, help="VNC host or IP")
    parser.add_argument(
        "--port", type=int, default=5900, help="VNC port (default 5900)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="VNC password; with --code, defaults to the code itself",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="screenshot.png",
        help="Screenshot output path (default screenshot.png)",
    )
    parser.add_argument(
        "--type",
        dest="type_text",
        default="hello",
        help="Text to type after capturing (default 'hello')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Connection timeout in seconds (default 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    host = args.host
    port = args.port
    password = args.password if args.password else None

    if args.code:
        code = normalize_code(args.code)
        logger.info("Looking for server with code %s...", args.code)
        info = find_server(code, timeout=args.timeout)
        if info is None:
            logger.error(
                "No server with that code found on the local network. "
                "Check the code, or use --host/--port to connect manually."
            )
            return 1
        logger.info("Found server %r at %s:%d", info.name, info.host, info.port)
        host, port = info.host, info.port
        # The built-in server uses the code as its password by default.
        if password is None:
            password = code
    elif not host:
        parser.error("either --code or --host is required")

    backend = VncdotoolBackend()

    try:
        logger.info("Connecting to %s:%d", host, port)
        backend.connect(host, port, password=password, timeout=args.timeout)

        logger.info("Capturing screenshot to %s", args.output)
        # get_frame is non-blocking; poll briefly until the first frame lands.
        frame = None
        deadline = time.monotonic() + args.timeout
        while frame is None and time.monotonic() < deadline:
            frame = backend.get_frame()
            if frame is None:
                time.sleep(0.1)
        if frame is None:
            logger.error("No frame received from server")
            return 1
        frame.save(args.output)

        text = args.type_text
        if text:
            logger.info("Typing text: %s", text)
            backend.send_text(text)

        logger.info("Done")
        return 0
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    finally:
        backend.disconnect()


if __name__ == "__main__":
    sys.exit(main())
