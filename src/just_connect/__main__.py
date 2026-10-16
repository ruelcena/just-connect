"""Allow running the app with ``python -m just_connect``."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
