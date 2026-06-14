#!/usr/bin/env python3
"""
make_icons.py — generate platform icon assets from assets/icon.svg.

Outputs:
  assets/icon.png        256×256  (Linux .desktop + fallback)
  assets/icon.ico        multi-resolution (Windows)
  assets/icon.iconset/   macOS iconset folder
  assets/icon.icns       macOS app icon  (requires macOS iconutil)

Run from the project root:
  python scripts/make_icons.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── resolve paths ────────────────────────────────────────────────────────────
ROOT   = Path(__file__).resolve().parent.parent
SVG    = ROOT / "assets" / "icon.svg"
ASSETS = ROOT / "assets"

if not SVG.exists():
    sys.exit(f"ERROR: {SVG} not found")

# ── render SVG → PIL Image via PyQt6 ─────────────────────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication          # noqa: E402
from PyQt6.QtSvg    import QSvgRenderer           # noqa: E402
from PyQt6.QtGui    import QPixmap, QPainter, QColor  # noqa: E402
from PyQt6.QtCore   import Qt, QSize              # noqa: E402
from PIL import Image                             # noqa: E402
import io                                         # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def render_svg(size: int) -> Image.Image:
    """Render icon.svg at `size`×`size` and return a PIL RGBA Image."""
    renderer = QSvgRenderer(str(SVG))
    pixmap   = QPixmap(QSize(size, size))
    pixmap.fill(QColor(0, 0, 0, 0))          # transparent background
    painter  = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    # QPixmap → PNG bytes → PIL Image
    buf = io.BytesIO()
    ba  = pixmap.toImage()
    ba.save(str(ASSETS / "_tmp.png"))         # write via Qt (lossless)
    img = Image.open(ASSETS / "_tmp.png").convert("RGBA")
    (ASSETS / "_tmp.png").unlink()
    return img


# ── sizes we need ────────────────────────────────────────────────────────────
ICO_SIZES     = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES    = [16, 32, 64, 128, 256, 512, 1024]
ICONSET_NAMES = {
    16:   ("icon_16x16.png",    "icon_16x16@2x.png"),    # 16 + 32
    32:   ("icon_32x32.png",    "icon_32x32@2x.png"),    # 32 + 64 (but we'll use 64 for @2x)
    128:  ("icon_128x128.png",  "icon_128x128@2x.png"),  # 128 + 256
    256:  ("icon_256x256.png",  "icon_256x256@2x.png"),  # 256 + 512
    512:  ("icon_512x512.png",  "icon_512x512@2x.png"),  # 512 + 1024
}

print("Rendering sizes …")
renders: dict[int, Image.Image] = {}
all_sizes = sorted(set(ICO_SIZES + ICNS_SIZES))
for s in all_sizes:
    print(f"  {s}×{s}")
    renders[s] = render_svg(s)

# ── assets/icon.png (256×256, Linux) ─────────────────────────────────────────
renders[256].save(ASSETS / "icon.png", "PNG")
print("✓ assets/icon.png")

# ── assets/icon.ico (Windows, multi-resolution) ──────────────────────────────
# Pillow resizes from the largest source image; pass the sizes list directly.
renders[max(ICO_SIZES)].save(
    ASSETS / "icon.ico",
    format="ICO",
    sizes=[(s, s) for s in ICO_SIZES],
)
print("✓ assets/icon.ico")

# ── assets/icon.iconset/ + icon.icns (macOS) ─────────────────────────────────
iconset = ASSETS / "icon.iconset"
iconset.mkdir(exist_ok=True)

# macOS iconset: each logical size needs a 1× and 2× file
iconset_map = {
    "icon_16x16.png":    16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png":    32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png":  128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png":  256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png":  512,
    "icon_512x512@2x.png": 1024,
}
for filename, size in iconset_map.items():
    renders[size].save(iconset / filename, "PNG")

print("✓ assets/icon.iconset/")

if sys.platform == "darwin":
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "icon.icns")],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("✓ assets/icon.icns")
    else:
        print(f"WARNING: iconutil failed — {result.stderr.strip()}")
        print("  Run 'iconutil -c icns assets/icon.iconset -o assets/icon.icns' manually.")
else:
    print("NOTE: icon.icns skipped (requires macOS iconutil). Copy iconset to a Mac and run:")
    print("  iconutil -c icns assets/icon.iconset -o assets/icon.icns")

print("\nDone. Commit the assets/ directory.")
