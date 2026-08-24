"""Entry point: `python -m voiceisland`."""

from __future__ import annotations

import sys

from voiceisland.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
