"""Shared pytest setup for the video_grid test suite.

Two jobs:

1. Mock out ``python-vlc`` before any test imports ``video_grid``. The
   real package tries to dlopen ``libvlc`` at import time, which we
   don't install on CI runners; the tests only exercise pure helper
   functions that never touch the VLC API anyway, so a ``MagicMock``
   stand-in is sufficient.

2. Put the project root on ``sys.path`` so ``import video_grid`` works
   regardless of where pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# 1. Mock the vlc module before video_grid imports it.
sys.modules.setdefault("vlc", MagicMock())

# 2. Make the project root importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
