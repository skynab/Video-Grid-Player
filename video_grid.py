#!/usr/bin/env python3
"""
Video Grid Player
-----------------
A cross-platform (Windows / macOS / Linux) desktop app that displays up
to 12 video files in a 4x3 grid with thumbnail previews. Click a cell to
play the video fullscreen INSIDE THE SAME APPLICATION. When the video
finishes (or Escape is pressed), the app returns to the grid view.

The folder picker is shown in a clean modal popup — either on startup
or from File -> Open Folder… — so the main window stays uncluttered.

Why PyQt6 (+ VLC)?
------------------
Tkinter on macOS cannot expose a usable NSView handle, which makes it
impossible to embed VLC video into a Tk window on Mac. PyQt6 widgets
give real native window handles on every platform (NSView on macOS,
HWND on Windows, X11 Window on Linux), so VLC can render video directly
into a QWidget everywhere — including macOS.

Dependencies
------------
  * Python 3.8+
  * VLC media player installed on the system
      - Windows : https://www.videolan.org/
      - macOS   : `brew install --cask vlc`  or download from videolan.org
      - Linux   : `sudo apt install vlc`     (or distro equivalent)
  * pip install PyQt6 python-vlc opencv-python
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
import tempfile
from pathlib import Path

from translations import LANGUAGES, get_strings

# Silence OpenCV's FFmpeg warning spam (e.g. "moov atom not found" that
# appears on some Windows setups when reading MP4s with non-ASCII paths).
# Must be set BEFORE cv2 is imported below to take effect.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")

# ---- dependency checks ----------------------------------------------------
_missing: list[str] = []
try:
    from PyQt6.QtCore import (
        Qt, QEvent, QPoint, QRectF, QSettings, QSize, QTimer, QThread,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPainterPath,
        QPalette, QPen, QPixmap, QRegion,
    )
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
        QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
        QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
        QVBoxLayout, QWidget,
    )
except ImportError:
    _missing.append("PyQt6")
try:
    import vlc
except ImportError:
    _missing.append("python-vlc")
try:
    import cv2
    import numpy as np
except ImportError:
    _missing.append("opencv-python")

if _missing:
    sys.stderr.write(
        "ERROR: missing Python dependencies: " + ", ".join(_missing) + "\n"
        "Install them with:\n"
        "    pip install " + " ".join(_missing) + "\n"
        "You also need VLC media player installed on your system.\n"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_GRID_COLS = 4
DEFAULT_GRID_ROWS = 3
MAX_GRID_DIM = 6                             # up to 6 rows / 6 cols each

VIDEO_EXTS = (
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".wmv", ".flv", ".m4v", ".mpg", ".mpeg", ".ts",
)

# Image extensions we'll look for when the "sidecar image" thumbnail
# option is enabled (e.g. `video.jpg` next to `video.mp4`).
SIDECAR_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# User-selectable thumbnail resolution. Each option names the maximum
# pixel footprint for decoded thumbnails; frames are scaled to fit inside
# this box while preserving aspect ratio. Higher resolutions look crisper
# on larger grid cells and high-DPI / 4K monitors at the cost of more
# memory and a slower initial decode.
#
#   Standard (640x360 / 360p)   - light and fast; fine for 1080p monitors
#                                 and dense grids (e.g. 6x6).
#   High     (1280x720 / 720p)  - great on 1080p, decent on 4K. Default.
#   Ultra    (1920x1080 / 1080p)- best on 4K / high-DPI; heaviest footprint.
THUMB_RES_STANDARD = "standard"
THUMB_RES_HIGH = "high"
THUMB_RES_ULTRA = "ultra"

THUMB_RESOLUTIONS: dict[str, tuple[int, int]] = {
    THUMB_RES_STANDARD: (640, 360),
    THUMB_RES_HIGH: (1280, 720),
    THUMB_RES_ULTRA: (1920, 1080),
}
THUMB_RES_LABELS: dict[str, str] = {
    THUMB_RES_STANDARD: "Standard (360p)",
    THUMB_RES_HIGH: "High (720p)",
    THUMB_RES_ULTRA: "Ultra (1080p)",
}
DEFAULT_THUMB_RES = THUMB_RES_HIGH


def thumb_size_for(resolution: str) -> tuple[int, int]:
    """Look up the (width, height) budget for a thumbnail resolution key,
    falling back to the default if the key is unknown."""
    return THUMB_RESOLUTIONS.get(resolution,
                                 THUMB_RESOLUTIONS[DEFAULT_THUMB_RES])


# Minimum on-screen size of each grid cell's thumbnail widget. This is
# about grid layout, not thumbnail quality — cells can scale up to the
# full decoded resolution when there's room.
THUMB_MIN_W = 320
THUMB_MIN_H = 180

# All title boxes in the grid are pinned to this height so they line up
# visually, regardless of whether a filename happens to be long or short.
TITLE_BAR_HEIGHT = 30

# How a thumbnail image should be rendered inside its grid cell.
# FIT_STRETCH stretches the image to completely fill the cell (ignoring
# the source's aspect ratio — this is the original behavior).
# FIT_CLIP scales the image to cover the cell while preserving the
# source's aspect ratio; any overflow is clipped.
FIT_STRETCH = "stretch"
FIT_CLIP = "clip"

# Multi-page fill-mode constants — controls what happens when the video
# count doesn't divide evenly into pages.
PAGE_FILL_BLANK    = "blank"     # last page shown with empty/blank cells
PAGE_FILL_ROUND_UP = "round_up"  # only complete pages shown; trailing videos dropped
PAGE_FILL_WRAP     = "wrap"      # last page padded by looping from the start


# ---------------------------------------------------------------------------
# Thumbnail cache (user-set "use this frame as thumbnail")
# ---------------------------------------------------------------------------
def _cache_dir() -> Path:
    """Per-user cache directory for custom thumbnails that the user has
    captured via the "Set as Thumbnail" button during playback."""
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "VideoGridPlayer" / "thumbs"
    return Path.home() / ".cache" / "video_grid_player" / "thumbs"


def _cached_thumb_path(video_path: str) -> Path:
    """Absolute filesystem path where the custom thumbnail for `video_path`
    is (or would be) stored. Keyed on the absolute video path so moving the
    video invalidates the cached thumb rather than misusing it."""
    key = hashlib.sha1(
        os.path.abspath(video_path).encode("utf-8", "replace")
    ).hexdigest()
    return _cache_dir() / (key + ".png")


def _find_sidecar_image(video_path: str) -> str | None:
    """If there's an image file sitting next to `video_path` whose name
    matches (e.g. `foo.mp4` <-> `foo.jpg`), return its path."""
    stem = os.path.splitext(video_path)[0]
    for ext in SIDECAR_IMAGE_EXTS:
        for candidate in (stem + ext, stem + ext.upper()):
            if os.path.isfile(candidate):
                return candidate
    return None


# ---------------------------------------------------------------------------
# Thumbnail extraction (runs on a worker thread)
# ---------------------------------------------------------------------------
def _cv_safe_path(path: str) -> str:
    """Return a path OpenCV's Windows file-open can handle without mangling
    non-ASCII characters.

    OpenCV on Windows opens files through its FFmpeg backend using the
    narrow (ANSI) Windows file APIs. Any non-ASCII character in the path
    is silently mistranscoded, so the underlying ``fopen`` ends up
    reading an entirely different file (or garbage), and FFmpeg reports
    the infamous ``moov atom not found`` even though the MP4 itself is
    perfectly fine. The reliable workaround is to translate the path to
    its Windows 8.3 short form, which is pure ASCII by construction.

    On non-Windows platforms the path is returned unchanged.
    """
    if sys.platform != "win32":
        return path
    abspath = os.path.abspath(path)
    # Fast path: if it's already plain ASCII, no translation needed.
    try:
        abspath.encode("ascii")
        return abspath
    except UnicodeEncodeError:
        pass
    try:
        import ctypes
        from ctypes import wintypes
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ]
        GetShortPathNameW.restype = wintypes.DWORD
        needed = GetShortPathNameW(abspath, None, 0)
        if needed > 0:
            buf = ctypes.create_unicode_buffer(needed)
            if GetShortPathNameW(abspath, buf, needed):
                return buf.value
    except Exception as exc:
        print(f"[thumbnail] short-path lookup failed for {abspath!r}: {exc}")
    return abspath


def _open_video_capture(path: str) -> "cv2.VideoCapture":
    """Open a video with OpenCV, trying several backends until one
    actually succeeds.

    Different OpenCV builds ship with different backends available, and
    on Windows in particular the default backend selection is
    occasionally broken for MP4s whose paths contain non-ASCII
    characters. We try FFmpeg first (most capable), then the platform
    default, then Media Foundation on Windows as a last resort.
    """
    safe = _cv_safe_path(path)
    backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]
    if sys.platform == "win32" and hasattr(cv2, "CAP_MSMF"):
        backends.append(cv2.CAP_MSMF)
    last: "cv2.VideoCapture | None" = None
    for backend in backends:
        try:
            cap = cv2.VideoCapture(safe, backend)
        except Exception as exc:
            print(f"[thumbnail] backend {backend} raised for {path!r}: {exc}")
            continue
        if cap.isOpened():
            return cap
        cap.release()
        last = None
    # Final fall-through: try the original (non-short) path with the
    # default backend, in case the short-path translation itself was the
    # problem (e.g. short names disabled on the volume).
    if safe != path:
        try:
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception as exc:
            print(f"[thumbnail] default-backend retry raised for {path!r}: {exc}")
    # Return a closed capture so callers can check isOpened() uniformly.
    return last if last is not None else cv2.VideoCapture()


def _fit_rgb_to_qimage(
    rgb: "np.ndarray",
    resolution: str = DEFAULT_THUMB_RES,
) -> "QImage":
    """Scale an RGB numpy image to fit within the thumbnail resolution's
    (W, H) budget while preserving aspect ratio, and return a QImage of
    exactly the scaled size (no letterbox / padding). The display widget
    decides later whether to stretch this to fill the cell or to
    scale-and-clip it."""
    max_w, max_h = thumb_size_for(resolution)
    h, w = rgb.shape[:2]
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    # tobytes() gives us a detached buffer so the returned QImage is safe
    # to keep around after the numpy array is freed.
    return QImage(
        resized.tobytes(), new_w, new_h, new_w * 3,
        QImage.Format.Format_RGB888,
    ).copy()


def extract_thumbnail(
    path: str,
    resolution: str = DEFAULT_THUMB_RES,
) -> "QImage | None":
    """Grab a representative frame from a video and return it as a
    QImage scaled (with aspect preserved) to fit within the budget for
    `resolution`.

    Returns None if no backend can open the file or no frame can be
    decoded — the caller treats that as "no thumbnail available" and
    leaves a placeholder in the grid cell.
    """
    cap = _open_video_capture(path)
    if not cap.isOpened():
        print(f"[thumbnail] could not open video: {path!r}")
        return None
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Skip a bit into the file to avoid black intros / studio logos.
        if total > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES,
                    max(1, min(total // 10, total - 1)))
        ok, frame = cap.read()
        if not ok or frame is None:
            # Some streams return False when seeking past the start; try
            # again from frame 0 before giving up.
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
    finally:
        cap.release()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return _fit_rgb_to_qimage(rgb, resolution)


def load_image_as_thumb_qimage(
    path: str,
    resolution: str = DEFAULT_THUMB_RES,
) -> "QImage | None":
    """Load an arbitrary image file (jpg/png/webp/bmp/...) and return a
    QImage scaled to fit within the chosen resolution's (W, H) budget
    while preserving aspect ratio. No padding is added — the display
    widget is responsible for deciding whether to stretch or clip the
    image inside its cell."""
    src = QImage(path)
    if src.isNull():
        return None
    src = src.convertToFormat(QImage.Format.Format_RGB888)
    max_w, max_h = thumb_size_for(resolution)
    return src.scaled(
        max_w, max_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def load_thumbnail_for_video(
    path: str, use_sidecar: bool,
    resolution: str = DEFAULT_THUMB_RES,
) -> "QImage | None":
    """Decide which thumbnail to show for a given video:

    1. A user-set thumbnail from the cache (captured via the "Set as
       Thumbnail" button during playback) always wins.
    2. If the sidecar option is on, try a matching image file sitting
       next to the video (e.g. `clip.jpg` beside `clip.mp4`).
    3. Otherwise fall back to extracting a frame from the video itself.
    """
    cached = _cached_thumb_path(path)
    if cached.is_file():
        img = load_image_as_thumb_qimage(str(cached), resolution)
        if img is not None:
            return img
    if use_sidecar:
        sidecar = _find_sidecar_image(path)
        if sidecar is not None:
            img = load_image_as_thumb_qimage(sidecar, resolution)
            if img is not None:
                return img
    return extract_thumbnail(path, resolution)


# Map our language codes to Google Translate target codes.
_LANG_TO_GOOGLE: dict[str, str] = {
    "en": "en",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "zh": "zh-CN",
    "ja": "ja",
    "ko": "ko",
}


def _translate_text(text: str, target: str) -> str:
    """Translate *text* to *target* using the free Google Translate endpoint.
    Returns the original text on any network or parse error."""
    import json
    import urllib.parse
    import urllib.request
    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=auto&dt=t&q="
        + urllib.parse.quote(text)
        + "&tl=" + urllib.parse.quote(target)
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Response shape: [[[translated, original, ...], ...], ...]
        parts = [seg[0] for seg in data[0] if seg[0]]
        return "".join(parts) or text
    except Exception:
        return text


class TitleTranslatorWorker(QThread):
    """Translate a batch of video titles off the GUI thread.

    Emits ``title_ready(idx, translated_text)`` for each title as soon as
    the translation comes back. Silently skips any title that fails."""
    title_ready = pyqtSignal(int, str)

    def __init__(self, titles: list[tuple[int, str]], target_lang: str):
        super().__init__()
        self._titles = titles          # [(grid_idx, raw_title), ...]
        self._target = _LANG_TO_GOOGLE.get(target_lang, target_lang)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        if self._target == "en":
            return
        for idx, raw in self._titles:
            if self._stop:
                break
            # Replace underscores/hyphens with spaces for better translation.
            cleaned = raw.replace("_", " ").replace("-", " ").strip()
            translated = _translate_text(cleaned, self._target)
            self.title_ready.emit(idx, translated)


class ThumbnailWorker(QThread):
    """Resolve thumbnails for a list of paths off the GUI thread.

    For each video we first check the user-set cache, then (optionally) a
    matching sidecar image, then fall back to decoding a frame from the
    video itself."""
    thumbnail_ready = pyqtSignal(int, str, QImage)

    def __init__(self, paths: list[str], use_sidecar: bool = False,
                 resolution: str = DEFAULT_THUMB_RES):
        super().__init__()
        self._paths = paths
        self._use_sidecar = use_sidecar
        self._resolution = resolution
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        for idx, path in enumerate(self._paths):
            if self._stop:
                return
            try:
                img = load_thumbnail_for_video(
                    path, self._use_sidecar, self._resolution)
            except Exception as exc:
                print(f"[thumbnail] error for {path!r}: {exc}")
                img = None
            if img is not None and not self._stop:
                self.thumbnail_ready.emit(idx, path, img)


# ---------------------------------------------------------------------------
# UI widgets
# ---------------------------------------------------------------------------
class SeekSlider(QSlider):
    """A QSlider that jumps directly to the clicked position (the default
    behavior only pages by one step), and emits a `seek_to` signal whenever
    the user changes the value via mouse interaction."""
    seek_to = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            if self.orientation() == Qt.Orientation.Horizontal:
                ratio = event.position().x() / max(1.0, float(self.width()))
            else:
                ratio = 1.0 - event.position().y() / max(1.0, float(self.height()))
            ratio = max(0.0, min(1.0, ratio))
            value = int(self.minimum()
                        + ratio * (self.maximum() - self.minimum()))
            self.setValue(value)
            self.seek_to.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.seek_to.emit(self.value())


def apply_rounded_mask(widget, radius: int) -> None:
    """Clip `widget` to a rounded-rectangle region so the rectangular
    area outside the rounded corners is not drawn at all.

    We need this because on macOS a widget with WA_NativeWindow gets its
    own NSView whose backing layer is opaque; Qt's `WA_TranslucentBackground`
    isn't enough to make the corners transparent in every case. `setMask()`
    clips at the native-window level, bypassing the alpha-blending path
    entirely, so the black square behind the rounded shape disappears.
    """
    if widget.width() <= 0 or widget.height() <= 0:
        return
    radius = max(0, min(radius, min(widget.width(), widget.height()) // 2))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, widget.width(), widget.height()),
                        radius, radius)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


def _make_loop_icon(size: int = 26) -> "QIcon":
    """White 'replay / loop' icon: a circle-arrow with a play triangle inside."""
    import math
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("white")
    lw = max(2, round(size * 0.10))
    pen = QPen(color, lw, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx, cy = size / 2, size / 2
    r = size * 0.38

    # Arc: ~300° starting from top-right, leaving a gap at the top for arrow
    start_deg = 80        # gap starts here (degrees, Qt: 0=3-o'clock, CCW)
    span_deg  = -300      # sweep clockwise
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    p.drawArc(rect,
              round(start_deg * 16),
              round(span_deg  * 16))

    # Arrowhead at the end of the arc (near the gap)
    end_rad = math.radians(start_deg + span_deg)  # in standard math coords
    # tip of the arrow on the circle
    tip_x = cx + r * math.cos(math.radians(start_deg + span_deg))
    tip_y = cy - r * math.sin(math.radians(start_deg + span_deg))
    # tangent direction (perpendicular to radius at tip), rotated for arrowhead
    tangent_angle = math.radians(start_deg + span_deg) + math.pi / 2
    arr = size * 0.20
    a1x = tip_x + arr * math.cos(tangent_angle + 0.55)
    a1y = tip_y - arr * math.sin(tangent_angle + 0.55)
    a2x = tip_x + arr * math.cos(tangent_angle - 0.55)
    a2y = tip_y - arr * math.sin(tangent_angle - 0.55)
    path = QPainterPath()
    path.moveTo(a1x, a1y)
    path.lineTo(tip_x, tip_y)
    path.lineTo(a2x, a2y)
    p.drawPath(path)

    # Play triangle in the centre
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    tri_r = size * 0.18
    tri_cx = cx + size * 0.03   # nudge right so it looks centred optically
    tri_cy = cy
    tri = QPainterPath()
    tri.moveTo(tri_cx - tri_r * 0.6, tri_cy - tri_r)
    tri.lineTo(tri_cx + tri_r,       tri_cy)
    tri.lineTo(tri_cx - tri_r * 0.6, tri_cy + tri_r)
    tri.closeSubpath()
    p.drawPath(tri)

    p.end()
    return QIcon(px)


def _make_checkmark_icon(size: int = 26) -> "QIcon":
    """White checkmark icon for the 'thumbnail set' confirmation state."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    lw = max(2, round(size * 0.12))
    pen = QPen(QColor("white"), lw, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = size
    p.drawLine(round(s * 0.18), round(s * 0.52),
               round(s * 0.42), round(s * 0.76))
    p.drawLine(round(s * 0.42), round(s * 0.76),
               round(s * 0.82), round(s * 0.26))
    p.end()
    return QIcon(px)


def _make_camera_icon(size: int = 40) -> "QIcon":
    """Draw a simple white camera icon at *size* × *size* px."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor("white")
    s = size
    lw = max(2, round(s * 0.07))
    pen = QPen(color, lw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # --- camera body ---------------------------------------------------
    pad    = round(s * 0.10)
    body_x = pad
    body_y = round(s * 0.30)
    body_w = s - 2 * pad
    body_h = round(s * 0.48)
    body_r = round(s * 0.12)
    p.drawRoundedRect(QRectF(body_x, body_y, body_w, body_h), body_r, body_r)

    # --- viewfinder bump on top ----------------------------------------
    bump_w = round(s * 0.28)
    bump_h = round(s * 0.12)
    bump_x = round(s * 0.5 - bump_w / 2)
    bump_y = body_y - bump_h + lw // 2
    p.drawRoundedRect(QRectF(bump_x, bump_y, bump_w, bump_h),
                      round(bump_h * 0.4), round(bump_h * 0.4))

    # --- lens (circle) -------------------------------------------------
    lens_r = round(s * 0.15)
    cx_l   = round(s * 0.5)
    cy_l   = round(body_y + body_h / 2)
    p.drawEllipse(QRectF(cx_l - lens_r, cy_l - lens_r, lens_r * 2, lens_r * 2))

    p.end()
    return QIcon(px)


class ThumbnailLabel(QLabel):
    """A QLabel that can render its pixmap in two different modes:

    * FIT_STRETCH - stretch the pixmap to fill the label, ignoring the
      source's aspect ratio. This matches QLabel's usual
      setScaledContents(True) behavior.
    * FIT_CLIP    - scale the pixmap to cover the label while preserving
      aspect ratio; any overflow on the major axis is clipped.

    While no pixmap is set (e.g. while thumbnails are still loading),
    painting falls back to the default QLabel rendering so placeholder
    text like "Loading thumbnail…" still shows up."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fit_mode: str = FIT_STRETCH
        self._src_pixmap: "QPixmap | None" = None

    def set_fit_mode(self, mode: str) -> None:
        self._fit_mode = mode
        self.update()

    def setPixmap(self, pixmap: "QPixmap") -> None:
        # We store the source and do all the rendering ourselves in
        # paintEvent, so deliberately don't forward to super().setPixmap
        # — otherwise QLabel would also try to draw the pixmap at its
        # natural size.
        if pixmap is None or pixmap.isNull():
            self._src_pixmap = None
        else:
            self._src_pixmap = pixmap
        self.update()

    def clear(self) -> None:
        self._src_pixmap = None
        super().clear()

    def paintEvent(self, event):
        # No pixmap yet — let QLabel handle text / placeholder painting.
        if self._src_pixmap is None or self._src_pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        aspect = (Qt.AspectRatioMode.IgnoreAspectRatio
                  if self._fit_mode == FIT_STRETCH
                  else Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        # Scale the source pixmap to the cell's *physical* pixel size,
        # not its logical size. On a 150% / 200% Windows display (or any
        # high-DPI monitor) self.size() reports logical pixels, so doing
        # a scale-to-self.size() leaves the pixmap under-resolved and Qt
        # has to upscale it again at paint time — that's the blur the
        # user sees as "low-resolution thumbnails on Windows". Setting
        # the scaled pixmap's devicePixelRatio tells the painter the
        # bitmap is already physical-sized so it paints 1:1.
        dpr = self.devicePixelRatioF() or 1.0
        target_w = max(1, int(self.width() * dpr))
        target_h = max(1, int(self.height() * dpr))
        scaled = self._src_pixmap.scaled(
            target_w, target_h,
            aspect,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        # scaled.size() is in physical pixels; convert back to logical
        # so the centering math matches the logical widget size.
        logical_w = scaled.width() / dpr
        logical_h = scaled.height() / dpr
        x = int((self.width() - logical_w) / 2)
        y = int((self.height() - logical_h) / 2)
        painter.drawPixmap(x, y, scaled)


class ClickableCell(QFrame):
    """A frame that emits `clicked` when left-clicked."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("videoCell")
        self.setStyleSheet(
            "#videoCell { background: #1e1e1e; border: 2px solid #333333; "
            "             border-radius: 6px; }"
            "#videoCell:hover { border: 2px solid #2b5fa1; }"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class OpenFolderDialog(QDialog):
    """Modal popup that prompts the user to pick a folder of videos,
    choose the grid dimensions, and toggle whether titles are shown
    under each thumbnail."""

    def __init__(self, parent=None,
                 show_titles_default: bool = True,
                 rows_default: int = DEFAULT_GRID_ROWS,
                 cols_default: int = DEFAULT_GRID_COLS,
                 full_width_default: bool = True,
                 use_sidecar_default: bool = False,
                 thumbnail_fit_default: str = FIT_STRETCH,
                 show_set_thumb_default: bool = True,
                 auto_hide_default: bool = False,
                 shuffle_default: bool = False,
                 multi_page_default: bool = False,
                 page_fill_default: str = PAGE_FILL_ROUND_UP,
                 thumbnail_resolution_default: str = DEFAULT_THUMB_RES,
                 chevron_hides_close_default: bool = True,
                 last_folder_default: str = "",
                 language_default: str = "en",
                 translate_titles_default: bool = False):
        super().__init__(parent)
        self._last_folder_default: str = last_folder_default or ""
        self.language: str = language_default
        self.translate_titles: bool = translate_titles_default
        tr = get_strings(self.language)
        self.setWindowTitle(tr["dialog_title"])
        self.setFixedSize(580, 660)
        self.setStyleSheet("QDialog { background: #101010; }")
        self.chosen_folder: str | None = None
        self.show_titles: bool = show_titles_default
        self.grid_rows: int = rows_default
        self.grid_cols: int = cols_default
        self.full_width: bool = full_width_default
        self.use_sidecar: bool = use_sidecar_default
        self.thumbnail_fit: str = thumbnail_fit_default
        self.show_set_thumb_button: bool = show_set_thumb_default
        self.auto_hide_overlays: bool = auto_hide_default
        self.shuffle_play: bool = shuffle_default
        self.multi_page: bool = multi_page_default
        self.page_fill: str = page_fill_default
        self.thumbnail_resolution: str = thumbnail_resolution_default
        self.chevron_hides_close_button: bool = chevron_hides_close_default

        # Outer layout: scroll area + button bar pinned at the bottom.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable content area so the dialog works on small screens.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #1a1a1a; width: 6px; "
            "                      border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #444; "
            "                              border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            "  { height: 0px; }"
        )
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 6, 22, 6)
        root.setSpacing(0)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # --- shared styles -----------------------------------------------
        label_style = (
            "color: #dddddd; font-size: 12px; background: transparent;"
        )
        combo_style = (
            "QComboBox {"
            "   background: #1a1a1a; color: white; "
            "   border: 1px solid #444; border-radius: 3px; "
            "   padding: 4px 8px; font-size: 12px; min-width: 160px;"
            "}"
            "QComboBox::drop-down {"
            "   border: none; width: 18px; "
            "}"
            "QComboBox QAbstractItemView {"
            "   background: #1a1a1a; color: white; "
            "   selection-background-color: #2b5fa1; "
            "   border: 1px solid #444;"
            "}"
        )
        spin_style = (
            "QSpinBox {"
            "   background: #1a1a1a; color: white; "
            "   border: 1px solid #444; border-radius: 3px; "
            "   padding: 4px 6px; font-size: 12px; min-width: 56px;"
            "}"
            "QSpinBox::up-button, QSpinBox::down-button {"
            "   background: #2a2a2a; border: none; width: 16px;"
            "}"
            "QSpinBox::up-button:hover, QSpinBox::down-button:hover {"
            "   background: #3a3a3a;"
            "}"
        )
        check_style = (
            "QCheckBox { color: #dddddd; font-size: 12px; "
            "            spacing: 8px; background: transparent; }"
            "QCheckBox::indicator { width: 16px; height: 16px; "
            "                       border-radius: 3px; "
            "                       border: 1px solid #666666; "
            "                       background: #1a1a1a; }"
            "QCheckBox::indicator:hover { border: 1px solid #888888; }"
            "QCheckBox::indicator:checked { "
            "   background: #2b5fa1; border: 1px solid #2b5fa1; "
            "   image: none; }"
        )
        section_style = (
            "color: white; font-size: 13px; font-weight: bold; "
            "background: transparent;"
        )
        divider_style = "background: #333333;"

        def add_section(key: str) -> QLabel:
            """Add a bold section title with a rule below it; return the label."""
            root.addSpacing(6)
            lbl = QLabel(tr[key])
            lbl.setStyleSheet(section_style)
            root.addWidget(lbl)
            rule = QFrame()
            rule.setFrameShape(QFrame.Shape.HLine)
            rule.setFixedHeight(1)
            rule.setStyleSheet(divider_style)
            root.addWidget(rule)
            root.addSpacing(4)
            return lbl

        def add_check(attr: str, tr_key: str, checked: bool,
                      enabled: bool = True, tip: str = "") -> QCheckBox:
            cb = QCheckBox(tr[tr_key])
            cb.setChecked(checked)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet(check_style)
            cb.setEnabled(enabled)
            if tip:
                cb.setToolTip(tip)
            root.addWidget(cb, 0, Qt.AlignmentFlag.AlignHCenter)
            root.addSpacing(3)
            return cb

        def add_combo_row(label_tr_key: str,
                          items: list[tuple[str, str]],
                          default_data: str) -> tuple:
            row = QHBoxLayout()
            row.addStretch(1)
            lbl = QLabel(tr[label_tr_key])
            lbl.setStyleSheet(label_style)
            row.addWidget(lbl)
            cb = QComboBox()
            cb.setStyleSheet(combo_style)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            for data, tr_key in items:
                cb.addItem(tr[tr_key], data)
            idx = cb.findData(default_data)
            cb.setCurrentIndex(max(0, idx))
            row.addWidget(cb)
            row.addStretch(1)
            root.addLayout(row)
            root.addSpacing(3)
            return lbl, cb

        # ═══════════════════════════════════════════════════════════════════
        # App title (centred, not a section header)
        # ═══════════════════════════════════════════════════════════════════
        self._sec_app = QLabel(tr["section_app"])
        self._sec_app.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sec_app.setStyleSheet(
            "color: white; font-size: 18px; font-weight: bold; "
            "background: transparent;")
        root.addWidget(self._sec_app)
        root.addSpacing(3)

        self._title_label = QLabel(tr["app_desc"])
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("color: #bbbbbb; font-size: 12px;")
        self._title_label.setWordWrap(True)
        root.addWidget(self._title_label)

        # ═══════════════════════════════════════════════════════════════════
        # Section: Language
        # ═══════════════════════════════════════════════════════════════════
        self._sec_language = add_section("section_language")

        lang_row = QHBoxLayout()
        lang_row.addStretch(1)
        self._lang_label = QLabel(tr["language_label"])
        self._lang_label.setStyleSheet(label_style)
        lang_row.addWidget(self._lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.setStyleSheet(combo_style)
        self.lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        lang_idx = self.lang_combo.findData(self.language)
        self.lang_combo.setCurrentIndex(max(0, lang_idx))
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch(1)
        root.addLayout(lang_row)
        root.addSpacing(3)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)

        self.translate_titles_checkbox = add_check(
            "translate_titles", "translate_titles", translate_titles_default)

        # ═══════════════════════════════════════════════════════════════════
        # Section: Video Grid
        # ═══════════════════════════════════════════════════════════════════
        self._sec_grid = add_section("section_grid")

        grid_row = QHBoxLayout()
        grid_row.addStretch(1)
        self._rows_label = QLabel(tr["rows_label"])
        self._rows_label.setStyleSheet(label_style)
        grid_row.addWidget(self._rows_label)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, MAX_GRID_DIM)
        self.rows_spin.setValue(rows_default)
        self.rows_spin.setStyleSheet(spin_style)
        grid_row.addWidget(self.rows_spin)
        grid_row.addSpacing(24)
        self._cols_label = QLabel(tr["cols_label"])
        self._cols_label.setStyleSheet(label_style)
        grid_row.addWidget(self._cols_label)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, MAX_GRID_DIM)
        self.cols_spin.setValue(cols_default)
        self.cols_spin.setStyleSheet(spin_style)
        grid_row.addWidget(self.cols_spin)
        grid_row.addStretch(1)
        root.addLayout(grid_row)
        root.addSpacing(4)

        self._res_label, self.res_combo = add_combo_row(
            "thumb_quality_label",
            [(THUMB_RES_STANDARD, "thumb_standard"),
             (THUMB_RES_HIGH,     "thumb_high"),
             (THUMB_RES_ULTRA,    "thumb_ultra")],
            thumbnail_resolution_default)
        # Correct selection in case the stored value wasn't found.
        if self.res_combo.currentIndex() < 0:
            self.res_combo.setCurrentIndex(
                max(0, self.res_combo.findData(DEFAULT_THUMB_RES)))

        self.titles_checkbox     = add_check("show_titles",  "show_titles",
                                             show_titles_default)
        self.full_width_checkbox = add_check("full_width",   "full_width",
                                             full_width_default)
        self.sidecar_checkbox    = add_check("use_sidecar",  "use_sidecar",
                                             use_sidecar_default)
        self.clip_thumb_checkbox = add_check("clip_thumb",   "clip_thumb",
                                             thumbnail_fit_default == FIT_CLIP)

        # ═══════════════════════════════════════════════════════════════════
        # Section: Video Grid Pages
        # ═══════════════════════════════════════════════════════════════════
        self._sec_pages = add_section("section_pages")

        self.multi_page_checkbox = add_check("multi_page", "multi_page",
                                             multi_page_default)

        self._page_fill_label, self.page_fill_combo = add_combo_row(
            "page_fill_label",
            [(PAGE_FILL_BLANK,    "page_fill_blank"),
             (PAGE_FILL_ROUND_UP, "page_fill_round_up"),
             (PAGE_FILL_WRAP,     "page_fill_wrap")],
            page_fill_default)

        # ═══════════════════════════════════════════════════════════════════
        # Section: Player
        # ═══════════════════════════════════════════════════════════════════
        self._sec_player = add_section("section_player")

        self.set_thumb_button_checkbox = add_check(
            "show_set_thumb_btn", "show_set_thumb_btn", show_set_thumb_default)
        self.auto_hide_checkbox = add_check(
            "auto_hide", "auto_hide", auto_hide_default)
        self.chevron_hides_close_checkbox = add_check(
            "chevron_hides_close", "chevron_hides_close",
            chevron_hides_close_default)
        self.shuffle_checkbox = add_check(
            "shuffle", "shuffle", shuffle_default)

        root.addSpacing(4)

        # ═══════════════════════════════════════════════════════════════════
        # Button bar — sits outside the scroll area, always visible
        # ═══════════════════════════════════════════════════════════════════
        btn_container = QWidget()
        btn_container.setStyleSheet(
            "background: #181818; border-top: 1px solid #2a2a2a;")
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setContentsMargins(22, 10, 22, 12)
        btn_layout.setSpacing(0)
        outer.addWidget(btn_container)

        # --- buttons (inside btn_container, always visible) ---------------
        self.chevron_hides_close_checkbox.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self.chevron_hides_close_checkbox.setStyleSheet(check_style)
        root.addWidget(self.chevron_hides_close_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(7)

        self.shuffle_checkbox = QCheckBox(tr["shuffle"])
        self.shuffle_checkbox.setChecked(shuffle_default)
        self.shuffle_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shuffle_checkbox.setStyleSheet(check_style)
        root.addWidget(self.shuffle_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(7)

        self.multi_page_checkbox = QCheckBox(tr["multi_page"])
        self.multi_page_checkbox.setChecked(multi_page_default)
        self.multi_page_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.multi_page_checkbox.setStyleSheet(check_style)
        root.addWidget(self.multi_page_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(14)

        # --- buttons ------------------------------------------------------
        row = QHBoxLayout()
        row.addStretch(1)

        self._choose_button = QPushButton(tr["choose_folder"])
        self._choose_button.setDefault(True)
        self._choose_button.setStyleSheet(
            "QPushButton { background: #2b5fa1; color: white; "
            "              font-weight: bold; padding: 9px 20px; "
            "              border: none; border-radius: 4px; }"
            "QPushButton:hover  { background: #3b7ec9; }"
            "QPushButton:pressed{ background: #24528b; }")
        self._choose_button.clicked.connect(self._choose_folder)
        row.addWidget(self._choose_button)

        # Reopens the most recently used folder without invoking the file
        # picker. Disabled when no previous folder has been recorded yet
        # or when the saved folder no longer exists on disk.
        self.reopen_button = QPushButton(tr["open_last"])
        self.reopen_button.setStyleSheet(
            "QPushButton { background: #444444; color: white; "
            "              padding: 9px 20px; border: none; "
            "              border-radius: 4px; }"
            "QPushButton:hover  { background: #555555; }"
            "QPushButton:pressed{ background: #333333; }"
            "QPushButton:disabled { background: #2a2a2a; color: #666666; }"
        )
        last_ok = bool(self._last_folder_default) and os.path.isdir(
            self._last_folder_default)
        self.reopen_button.setEnabled(last_ok)
        if last_ok:
            self.reopen_button.setToolTip(
                tr["reopen_tip"].format(folder=self._last_folder_default))
        else:
            self.reopen_button.setToolTip(
                tr["no_last_folder_tip"])
        self.reopen_button.clicked.connect(self._reopen_last_folder)
        row.addWidget(self.reopen_button)

        self._cancel_button = QPushButton(tr["cancel"])
        self._cancel_button.setStyleSheet(
            "QPushButton { background: #333333; color: white; "
            "              padding: 9px 20px; border: none; "
            "              border-radius: 4px; }"
            "QPushButton:hover { background: #444444; }")
        self._cancel_button.clicked.connect(self.reject)
        row.addWidget(self._cancel_button)

        row.addStretch(1)
        btn_layout.addLayout(row)

    def _on_language_changed(self) -> None:
        code = self.lang_combo.currentData()
        if code and code != self.language:
            self.language = code
            self._retranslate()

    def _retranslate(self) -> None:
        """Update every translatable widget text to the current language."""
        tr = get_strings(self.language)
        self.setWindowTitle(tr["dialog_title"])
        # Section headers
        self._sec_app.setText(tr["section_app"])
        self._sec_language.setText(tr["section_language"])
        self._sec_grid.setText(tr["section_grid"])
        self._sec_pages.setText(tr["section_pages"])
        self._sec_player.setText(tr["section_player"])
        # App description (repurposed as _title_label)
        self._title_label.setText(tr["app_desc"])
        # Language section
        self._lang_label.setText(tr["language_label"])
        self.translate_titles_checkbox.setText(tr["translate_titles"])
        # Grid section
        self._rows_label.setText(tr["rows_label"])
        self._cols_label.setText(tr["cols_label"])
        self._res_label.setText(tr["thumb_quality_label"])
        for i, tr_key in enumerate(("thumb_standard", "thumb_high", "thumb_ultra")):
            self.res_combo.setItemText(i, tr[tr_key])
        self.titles_checkbox.setText(tr["show_titles"])
        self.full_width_checkbox.setText(tr["full_width"])
        self.sidecar_checkbox.setText(tr["use_sidecar"])
        self.clip_thumb_checkbox.setText(tr["clip_thumb"])
        # Pages section
        self.multi_page_checkbox.setText(tr["multi_page"])
        self._page_fill_label.setText(tr["page_fill_label"])
        for i, tr_key in enumerate(
                ("page_fill_blank", "page_fill_round_up", "page_fill_wrap")):
            self.page_fill_combo.setItemText(i, tr[tr_key])
        # Player section
        self.set_thumb_button_checkbox.setText(tr["show_set_thumb_btn"])
        self.auto_hide_checkbox.setText(tr["auto_hide"])
        self.chevron_hides_close_checkbox.setText(tr["chevron_hides_close"])
        self.shuffle_checkbox.setText(tr["shuffle"])
        self.multi_page_checkbox.setText(tr["multi_page"])
        # Buttons
        self._choose_button.setText(tr["choose_folder"])
        self.reopen_button.setText(tr["open_last"])
        self._cancel_button.setText(tr["cancel"])
        # Reopen tooltip
        last_ok = bool(self._last_folder_default) and os.path.isdir(
            self._last_folder_default)
        if last_ok:
            self.reopen_button.setToolTip(
                tr["reopen_tip"].format(folder=self._last_folder_default))
        else:
            self.reopen_button.setToolTip(tr["no_last_folder_tip"])

    def _commit_widget_values(self) -> None:
        """Pull the current state of every option widget into this
        dialog's public attributes. Shared by the Choose Folder and
        Open Last Folder paths so both honor any tweaks the user made
        in the popup before clicking."""
        self.show_titles = self.titles_checkbox.isChecked()
        self.grid_rows = self.rows_spin.value()
        self.grid_cols = self.cols_spin.value()
        self.full_width = self.full_width_checkbox.isChecked()
        self.use_sidecar = self.sidecar_checkbox.isChecked()
        self.thumbnail_fit = (
            FIT_CLIP if self.clip_thumb_checkbox.isChecked()
            else FIT_STRETCH)
        self.show_set_thumb_button = (
            self.set_thumb_button_checkbox.isChecked())
        self.auto_hide_overlays = self.auto_hide_checkbox.isChecked()
        self.chevron_hides_close_button = (
            self.chevron_hides_close_checkbox.isChecked())
        self.shuffle_play = self.shuffle_checkbox.isChecked()
        self.multi_page = self.multi_page_checkbox.isChecked()
        fill_key = self.page_fill_combo.currentData()
        if fill_key in (PAGE_FILL_BLANK, PAGE_FILL_ROUND_UP, PAGE_FILL_WRAP):
            self.page_fill = fill_key
        self.translate_titles = self.translate_titles_checkbox.isChecked()
        res_key = self.res_combo.currentData()
        if res_key in THUMB_RESOLUTIONS:
            self.thumbnail_resolution = res_key
        lang_key = self.lang_combo.currentData()
        if lang_key in LANGUAGES:
            self.language = lang_key

    def _choose_folder(self) -> None:
        # Default the OS picker to the last folder we used, if it still
        # exists; otherwise fall back to the user's home directory.
        start_dir = (self._last_folder_default
                     if self._last_folder_default
                     and os.path.isdir(self._last_folder_default)
                     else os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(
            self, "Select a folder of videos", start_dir)
        if folder:
            self.chosen_folder = folder
            self._commit_widget_values()
            self.accept()

    def _reopen_last_folder(self) -> None:
        """Skip the file picker and reuse the previously selected folder.
        Refuses (and disables itself) if the path is missing — that can
        happen if the folder was renamed/moved between sessions."""
        target = self._last_folder_default
        if not target or not os.path.isdir(target):
            self.reopen_button.setEnabled(False)
            self.reopen_button.setToolTip(
                "Previous folder is no longer available.")
            return
        self.chosen_folder = target
        self._commit_widget_values()
        self.accept()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class VideoGridApp(QMainWindow):
    def __init__(self, initial_folder: str | None = None):
        super().__init__()
        self.setWindowTitle("Video Grid Player")
        self.resize(1400, 900)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(
            "QMainWindow { background: #101010; }"
            "QLabel      { color: white; }"
        )

        # VLC.
        # On Windows we pass a few extra options:
        #   --vout=direct3d9  is the well-tested Direct3D9 output. It
        #     honors HWND z-order (so our overlay controls stay on top)
        #     AND doesn't call the DWM's SetThumbNailClip API that the
        #     newer direct3d11 vout uses. That call fails with
        #     0x800706f4 (RPC_X_NULL_REF_POINTER) on embedded child
        #     HWNDs like ours, and its error path can wedge VLC's
        #     cleanup when a video ends, causing the whole app to hang.
        #   --no-mouse-events / --no-keyboard-events  stop VLC from
        #     swallowing clicks and keys on its own video window so events
        #     fall through to our overlay buttons.
        vlc_args = ["--no-video-title-show"]
        if sys.platform == "win32":
            vlc_args += [
                "--vout=direct3d9",
                "--no-mouse-events",
                "--no-keyboard-events",
            ]
        self.vlc_instance = vlc.Instance(vlc_args)
        self.player = self.vlc_instance.media_player_new()
        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached,
                        self._on_vlc_end)
        em.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                        self._on_vlc_end)
        em.event_attach(vlc.EventType.MediaPlayerPaused,
                        self._on_vlc_paused)
        em.event_attach(vlc.EventType.MediaPlayerPlaying,
                        self._on_vlc_playing)

        # State
        self.video_files: list[str] = []
        self.thumbnails: dict[str, QPixmap] = {}
        self.cell_widgets: list[dict | None] = []
        self.is_playing = False
        self.thumb_worker: ThumbnailWorker | None = None
        self.show_titles: bool = True     # toggled via the open-folder popup
        self.grid_rows: int = DEFAULT_GRID_ROWS
        self.grid_cols: int = DEFAULT_GRID_COLS
        self.full_width: bool = True      # edge-to-edge layout with no gaps
        self.use_sidecar_thumbnails: bool = False  # use foo.jpg next to foo.mp4
        self.thumbnail_fit: str = FIT_STRETCH     # how thumbnails fill cells
        self.show_set_thumb_button: bool = True   # show/hide overlay button
        self.auto_hide_overlays: bool = False     # auto-hide after 5 seconds
        self._overlays_hidden: bool = False       # current hide/show state
        self.shuffle_play: bool = False           # play random next on end
        self.multi_page: bool = False             # show all videos across pages
        self.page_fill: str = PAGE_FILL_ROUND_UP  # fill-mode for uneven pages
        self.translate_titles: bool = False       # translate filenames via API
        self.title_worker: TitleTranslatorWorker | None = None
        self.all_video_files: list[str] = []      # full unsliced video list
        self.current_page: int = 0                # 0-based page index
        self.thumbnail_resolution: str = DEFAULT_THUMB_RES  # decoded thumb size
        self.chevron_hides_close_button: bool = True  # ✕ vanishes on collapse?
        self.last_folder: str = ""  # most recent folder loaded; "" if none yet
        self.language: str = "en"  # UI language code
        # Remembered window state across a play→stop cycle. Populated in
        # _play_video_at so we can restore the pre-playback window state
        # (fullscreen / maximized / normal) when playback ends.
        self._was_fullscreen_before_play: bool = False
        self._was_maximized_before_play: bool = False
        self.current_video_path: str | None = None
        self.current_video_idx: int | None = None

        # Load any preferences saved on a previous run, so the open-folder
        # popup comes up pre-filled with the user's last-used choices.
        self._load_preferences()

        # Central pages (grid / video) in a stack
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_menu()
        self._build_grid_page()
        self._build_video_page()
        self._build_close_overlay()
        self._build_set_thumb_overlay()
        self._build_loop_overlay()
        self._build_jog_overlay()
        self._build_overlay_toggle()
        self._build_page_arrows()
        self._build_auto_hide_timer()
        self.stack.setCurrentWidget(self.grid_page)

        self._render_grid()

        # Initial folder or popup picker
        if initial_folder and os.path.isdir(initial_folder):
            QTimer.singleShot(100, lambda: self._load_folder(initial_folder))
        else:
            QTimer.singleShot(250, self._show_open_dialog)

    # ------------------------------------------------------------------ UI --
    def _build_menu(self) -> None:
        menu = self.menuBar()

        self._file_menu = menu.addMenu(self._tr("menu_file"))
        self._open_act = QAction(self._tr("menu_open_folder"), self)
        self._open_act.setShortcut(QKeySequence.StandardKey.Open)
        self._open_act.triggered.connect(self._show_open_dialog)
        self._file_menu.addAction(self._open_act)
        self._file_menu.addSeparator()
        # Full Screen toggle. Checkable so the menu reflects the current
        # state. Uses the platform standard shortcut (F11 on Windows/Linux,
        # Ctrl+Cmd+F on macOS).
        self.fullscreen_act = QAction(self._tr("menu_fullscreen"), self)
        self.fullscreen_act.setCheckable(True)
        self.fullscreen_act.setShortcut(QKeySequence.StandardKey.FullScreen)
        self.fullscreen_act.triggered.connect(self._toggle_fullscreen)
        self._file_menu.addAction(self.fullscreen_act)
        self._file_menu.addSeparator()
        self._exit_act = QAction(self._tr("menu_quit"), self)
        self._exit_act.setShortcut(QKeySequence.StandardKey.Quit)
        self._exit_act.triggered.connect(self.close)
        self._file_menu.addAction(self._exit_act)

        help_menu = menu.addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _retranslate_menu(self) -> None:
        """Update menu item text to the current language."""
        self._file_menu.setTitle(self._tr("menu_file"))
        self._open_act.setText(self._tr("menu_open_folder"))
        self.fullscreen_act.setText(self._tr("menu_fullscreen"))
        self._exit_act.setText(self._tr("menu_quit"))

    def _build_grid_page(self) -> None:
        self.grid_page = QWidget()
        layout = QGridLayout(self.grid_page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.grid_layout = layout
        self.stack.addWidget(self.grid_page)

    def _build_video_page(self) -> None:
        self.video_page = QWidget()
        v = QVBoxLayout(self.video_page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # A bare QWidget for VLC to render into.  WA_NativeWindow forces
        # Qt to create the underlying native surface (NSView on macOS,
        # HWND on Windows, X11 window on Linux) eagerly, so winId() is
        # valid before the page is shown.
        self.video_surface = QWidget()
        self.video_surface.setAttribute(
            Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_surface.setAttribute(
            Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.video_surface.setAutoFillBackground(True)
        pal = self.video_surface.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.video_surface.setPalette(pal)
        v.addWidget(self.video_surface)

        self.stack.addWidget(self.video_page)

    # --------- overlay window helpers ---------------------------------------
    def _promote_to_overlay_window(self, widget) -> None:
        """Make `widget` a top-level frameless Tool window that floats
        above the main window.

        Rationale: on Windows, even with WA_NativeWindow + raise_(), the
        VLC video surface (a hardware-accelerated child HWND) can end up
        drawn above sibling HWNDs in ways that hide our overlay controls.
        Promoting the controls to separate top-level windows gives each
        one its own HWND at a different level of the window hierarchy,
        where it is trivially above the main window's content on every
        platform. The widget keeps the main window as its Qt parent, so
        Qt automatically hides/shows it with the parent and it doesn't
        get a taskbar entry (because of Qt.Tool).

        CustomizeWindowHint tells Qt to honor ONLY the hints we've set
        here — without it, Windows still draws a thin gray client-edge
        border around the window even though FramelessWindowHint is on.
        """
        widget.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        widget.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        widget.setAutoFillBackground(False)

    def _paint_main_window_border_black(self) -> None:
        """On Windows 11, every top-level window gets a 1px accent-color
        border *and* 8px rounded corners painted by DWM. In fullscreen
        the border shows as a thin transparent/colored seam, and the
        rounded corners leave small gaps in each corner that don't
        belong in a fullscreen video player.

        Tell DWM to paint the border black (blends into the dark app
        background) and to not round corners. Re-applied on every
        window state change because Windows sometimes resets these
        attributes during fullscreen transitions.

        No-op on macOS / Linux / Windows 10 and below.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            dwmapi = ctypes.windll.dwmapi
            # Set argtypes explicitly: on 64-bit Windows, HWND is 8 bytes
            # but ctypes defaults to c_int (4 bytes), which truncates the
            # handle and causes the call to silently target the wrong
            # window (or fail).
            dwmapi.DwmSetWindowAttribute.argtypes = [
                wintypes.HWND, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD,
            ]
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT

            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWA_BORDER_COLOR = 34
            DWMWCP_DONOTROUND = 1
            hwnd = int(self.winId())

            # COLORREF for black is 0x00000000 (0x00BBGGRR). This paints
            # the 1px DWM border black instead of the system accent color
            # so it vanishes into our dark background in fullscreen.
            black = ctypes.c_uint(0x00000000)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR,
                ctypes.byref(black), ctypes.sizeof(black))

            # Force square corners. Without this, Windows 11 rounds the
            # corners even in fullscreen, leaving transparent gaps in
            # each corner of the screen.
            corner_pref = ctypes.c_int(DWMWCP_DONOTROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
        except Exception:
            # Older Windows (10 and below) doesn't expose these
            # attributes; the calls return E_INVALIDARG harmlessly.
            pass

    def _strip_native_window_border(self, widget) -> None:
        """On Windows, explicitly remove the extended window styles that
        draw a thin gray edge around top-level windows. Must be called
        after the widget's native HWND exists (i.e. after show()).

        No-op on macOS / Linux.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = int(widget.winId())
            GWL_EXSTYLE = -20
            WS_EX_CLIENTEDGE = 0x00000200
            WS_EX_STATICEDGE = 0x00020000
            WS_EX_DLGMODALFRAME = 0x00000001
            WS_EX_WINDOWEDGE = 0x00000100
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            GetWindowLongW = user32.GetWindowLongW
            GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            GetWindowLongW.restype = ctypes.c_long
            SetWindowLongW = user32.SetWindowLongW
            SetWindowLongW.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_long]
            SetWindowLongW.restype = ctypes.c_long
            ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_ex = ex & ~(
                WS_EX_CLIENTEDGE
                | WS_EX_STATICEDGE
                | WS_EX_DLGMODALFRAME
                | WS_EX_WINDOWEDGE
            )
            if new_ex != ex:
                SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                    | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
        except Exception as exc:
            print(f"[overlay] could not strip window border: {exc}")

        # Windows 11 paints a thin 1px "accent color" border around every
        # top-level window by default, even frameless ones. The only way
        # to remove it is to tell DWM to use DWMWA_COLOR_NONE for the
        # border color, and to disable Windows 11's automatic rounded
        # corners (we draw our own via setMask). These attributes don't
        # exist pre-Windows-11 — the calls just return E_INVALIDARG and
        # are harmless.
        try:
            import ctypes
            dwmapi = ctypes.windll.dwmapi
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWA_BORDER_COLOR = 34
            DWMWCP_DONOTROUND = 1
            DWMWA_COLOR_NONE = 0xFFFFFFFE
            corner_pref = ctypes.c_int(DWMWCP_DONOTROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
            border_color = ctypes.c_uint(DWMWA_COLOR_NONE)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR,
                ctypes.byref(border_color), ctypes.sizeof(border_color))
        except Exception:
            # Older Windows (10 and below) doesn't expose these
            # attributes; silently fall through.
            pass

    def _place_overlay(self, widget, x_local: int, y_local: int) -> None:
        """Move a promoted top-level overlay to `(x_local, y_local)` given
        in this window's local coordinate space. Because overlays are
        top-level windows, `move()` takes global screen coordinates — so
        we translate before moving."""
        gp = self.mapToGlobal(QPoint(max(0, x_local), max(0, y_local)))
        widget.move(gp)

    def _build_close_overlay(self) -> None:
        """Floating X button shown over the video while playing.

        Implemented as a top-level frameless Tool window so it reliably
        floats above VLC's native video surface on every platform.
        """
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("closeOverlay")
        self.close_button.setFixedSize(48, 48)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip(self._tr("close_tip"))
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._promote_to_overlay_window(self.close_button)
        self.close_button.setStyleSheet(
            "#closeOverlay {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  color: white;"
            "  border: none;"
            "  border-radius: 24px;"
            "  font-size: 22px;"
            "  font-weight: bold;"
            "}"
            "#closeOverlay:hover {"
            "  background-color: rgba(210, 50, 50, 220);"
            "}"
            "#closeOverlay:pressed {"
            "  background-color: rgba(170, 30, 30, 230);"
            "}"
        )
        self.close_button.clicked.connect(self._stop_playback)
        # Clip to a 48×48 circle so macOS's opaque native backing doesn't
        # show as a black square around the X.
        apply_rounded_mask(self.close_button, 24)
        self.close_button.hide()

    def _position_close_button(self) -> None:
        """Pin the close button to the top-right corner of the window."""
        margin = 20
        x = self.width() - self.close_button.width() - margin
        y = margin
        self._place_overlay(self.close_button, x, y)
        self.close_button.raise_()

    # ---------------------------------------------- "Set Thumbnail" overlay --
    def _build_set_thumb_overlay(self) -> None:
        """A pill-shaped button overlaid on the top-right of the video that
        captures the current frame and uses it as the grid thumbnail for
        the video being played. It sits just to the left of the ✕ button.
        """
        self.set_thumb_button = QPushButton(self)
        self.set_thumb_button.setObjectName("setThumbOverlay")
        self.set_thumb_button.setFixedSize(40, 40)
        self.set_thumb_button.setIcon(_make_camera_icon(26))
        self.set_thumb_button.setIconSize(QSize(26, 26))
        self.set_thumb_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_thumb_button.setToolTip(self._tr("thumb_tip"))
        self.set_thumb_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._promote_to_overlay_window(self.set_thumb_button)
        self.set_thumb_button.setStyleSheet(
            "#setThumbOverlay {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  border: none;"
            "  border-radius: 20px;"
            "  padding: 0;"
            "}"
            "#setThumbOverlay:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "}"
            "#setThumbOverlay:pressed {"
            "  background-color: rgba(36, 82, 139, 230);"
            "}"
        )
        self.set_thumb_button.clicked.connect(
            self._capture_current_frame_as_thumbnail)
        self.set_thumb_button.hide()

    def _position_set_thumb_button(self) -> None:
        """Pin the 'Set Thumbnail' button just to the left of the ✕ button."""
        margin = 20
        gap = 12
        # Compute the close button's position in OUR local coord space
        # (close_button is a top-level window, so its .x()/.y() are global).
        close_local = self.mapFromGlobal(
            QPoint(self.close_button.x(), self.close_button.y()))
        x = close_local.x() - self.set_thumb_button.width() - gap
        y = margin + (self.close_button.height() - 40) // 2
        self._place_overlay(self.set_thumb_button, x, y)
        apply_rounded_mask(self.set_thumb_button, 20)
        self.set_thumb_button.raise_()

    # --------------------------------------------------- loop/replay button --
    def _build_loop_overlay(self) -> None:
        """Floating loop button in the top-left corner of the video.
        When active the video restarts automatically when it ends."""
        self.loop_active: bool = False
        self.loop_button = QPushButton(self)
        self.loop_button.setObjectName("loopOverlay")
        self.loop_button.setFixedSize(40, 40)
        self.loop_button.setIcon(_make_loop_icon(24))
        self.loop_button.setIconSize(QSize(24, 24))
        self.loop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.loop_button.setToolTip(self._tr("loop_off_tip"))
        self.loop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._promote_to_overlay_window(self.loop_button)
        self._apply_loop_button_style()
        self.loop_button.clicked.connect(self._toggle_loop)
        apply_rounded_mask(self.loop_button, 20)
        self.loop_button.hide()

    def _apply_loop_button_style(self) -> None:
        if self.loop_active:
            self.loop_button.setStyleSheet(
                "#loopOverlay {"
                "  background-color: rgba(43, 95, 161, 210);"
                "  border: none;"
                "  border-radius: 20px;"
                "  padding: 0;"
                "}"
                "#loopOverlay:hover {"
                "  background-color: rgba(59, 126, 201, 230);"
                "}"
                "#loopOverlay:pressed {"
                "  background-color: rgba(36, 82, 139, 240);"
                "}"
            )
        else:
            self.loop_button.setStyleSheet(
                "#loopOverlay {"
                "  background-color: rgba(0, 0, 0, 170);"
                "  border: none;"
                "  border-radius: 20px;"
                "  padding: 0;"
                "}"
                "#loopOverlay:hover {"
                "  background-color: rgba(43, 95, 161, 220);"
                "}"
                "#loopOverlay:pressed {"
                "  background-color: rgba(36, 82, 139, 230);"
                "}"
            )

    def _toggle_loop(self) -> None:
        self.loop_active = not self.loop_active
        self._apply_loop_button_style()
        state = self._tr("loop_on") if self.loop_active else self._tr("loop_off")
        self.loop_button.setToolTip(
            self._tr("loop_tip_fmt").format(state=state))

    def _position_loop_button(self) -> None:
        """Pin the loop button just to the left of the camera button (or the
        ✕ button if the camera button is hidden)."""
        gap = 12
        margin = 20
        if self.set_thumb_button.isVisible():
            anchor = self.mapFromGlobal(
                QPoint(self.set_thumb_button.x(), self.set_thumb_button.y()))
        else:
            anchor = self.mapFromGlobal(
                QPoint(self.close_button.x(), self.close_button.y()))
        x = anchor.x() - self.loop_button.width() - gap
        y = margin + (self.close_button.height() - 40) // 2
        self._place_overlay(self.loop_button, x, y)
        apply_rounded_mask(self.loop_button, 20)
        self.loop_button.raise_()

    # ------------------------------------------------ jog / transport bar --
    def _build_jog_overlay(self) -> None:
        """Floating bottom transport bar with current time, scrubber slider,
        and total time. Composited over the VLC video output the same way
        the close button is — child of the main window with its own
        native surface so it draws cleanly on top of native video."""
        self.jog_bar = QWidget(self)
        self.jog_bar.setObjectName("jogBar")
        self._promote_to_overlay_window(self.jog_bar)
        self.jog_bar.setStyleSheet(
            "#jogBar { background-color: rgba(0, 0, 0, 180); "
            "          border-radius: 10px; }"
        )

        bar_layout = QHBoxLayout(self.jog_bar)
        bar_layout.setContentsMargins(18, 10, 18, 10)
        bar_layout.setSpacing(14)

        # Pause / resume button — lives at the left end of the transport
        # bar. Uses Unicode media glyphs (⏸ / ▶) so we don't need an icon
        # file. The button toggles VLC's paused state; its label is also
        # kept in sync with VLC via MediaPlayerPaused/Playing events so it
        # still reflects reality when Space is used instead.
        self.pause_button = QPushButton("\u23F8")
        self.pause_button.setObjectName("pauseBtn")
        self.pause_button.setFixedSize(36, 36)
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pause_button.setToolTip("Pause / resume (Space)")
        self.pause_button.setStyleSheet(
            "#pauseBtn {"
            "  background-color: rgba(255, 255, 255, 30);"
            "  color: white;"
            "  border: none;"
            "  border-radius: 18px;"
            "  font-size: 15px;"
            "  padding: 0;"
            "}"
            "#pauseBtn:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "}"
            "#pauseBtn:pressed {"
            "  background-color: rgba(36, 82, 139, 230);"
            "}"
        )
        self.pause_button.clicked.connect(self._toggle_pause)
        bar_layout.addWidget(self.pause_button)

        self.time_current = QLabel("0:00")
        self.time_current.setStyleSheet(
            "color: white; font-size: 12px; font-family: monospace; "
            "background: transparent; border: none;")
        self.time_current.setMinimumWidth(54)
        self.time_current.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar_layout.addWidget(self.time_current)

        self.timeline = SeekSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 1000)  # 0.1% granularity
        self.timeline.setSingleStep(5)
        self.timeline.setPageStep(50)
        self.timeline.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timeline.setStyleSheet(
            "QSlider::groove:horizontal {"
            "   height: 6px;"
            "   background: rgba(255, 255, 255, 50);"
            "   border-radius: 3px;"
            "}"
            "QSlider::sub-page:horizontal {"
            "   background: #2b5fa1;"
            "   border-radius: 3px;"
            "}"
            "QSlider::handle:horizontal {"
            "   background: white;"
            "   width: 16px;"
            "   height: 16px;"
            "   margin: -5px 0;"
            "   border-radius: 8px;"
            "}"
            "QSlider::handle:horizontal:hover {"
            "   background: #b9d2f3;"
            "}"
        )
        self.timeline.seek_to.connect(self._on_user_seek)
        bar_layout.addWidget(self.timeline, 1)

        self.time_total = QLabel("0:00")
        self.time_total.setStyleSheet(
            "color: white; font-size: 12px; font-family: monospace; "
            "background: transparent; border: none;")
        self.time_total.setMinimumWidth(54)
        self.time_total.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bar_layout.addWidget(self.time_total)

        self.jog_bar.hide()

        # 5 Hz polling — cheap and smooth enough for a scrubber.
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(200)
        self.position_timer.timeout.connect(self._update_position)

    def _position_jog_bar(self) -> None:
        """Pin the transport bar to the bottom-center of the window."""
        margin_x = 40
        # Leave enough room below the jog bar for the chevron toggle to
        # sit "under the timeline" without falling off the screen.
        margin_y = 52
        bar_height = 56
        bar_width = max(360, self.width() - 2 * margin_x)
        self.jog_bar.setFixedHeight(bar_height)
        self.jog_bar.setFixedWidth(bar_width)
        x = (self.width() - bar_width) // 2
        y = self.height() - bar_height - margin_y
        self._place_overlay(self.jog_bar, x, y)
        # Re-mask on every resize so the rounded pill shape stays clipped
        # instead of leaking a black rectangle over the video on macOS.
        apply_rounded_mask(self.jog_bar, 10)
        self.jog_bar.raise_()

    # ------------------------------------------ chevron hide/show toggle --
    def _build_overlay_toggle(self) -> None:
        """A small pill-shaped button anchored just below the timeline.
        Pressing it hides every on-screen control (timeline, pause, close,
        "Set Thumbnail") leaving only this button visible, which now shows
        an up-chevron so it can restore the controls on the next press."""
        self.overlay_toggle = QPushButton("\u25BE", self)   # ▾
        self.overlay_toggle.setObjectName("overlayToggle")
        self.overlay_toggle.setFixedSize(56, 28)
        self.overlay_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overlay_toggle.setToolTip(self._tr("hide_controls_tip"))
        self._promote_to_overlay_window(self.overlay_toggle)
        self.overlay_toggle.setStyleSheet(
            "#overlayToggle {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  color: white;"
            "  border: none;"
            "  border-radius: 14px;"
            "  font-size: 16px;"
            "  font-weight: bold;"
            "  padding: 0;"
            "}"
            "#overlayToggle:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "}"
            "#overlayToggle:pressed {"
            "  background-color: rgba(36, 82, 139, 230);"
            "}"
        )
        self.overlay_toggle.clicked.connect(self._toggle_overlays)
        apply_rounded_mask(self.overlay_toggle, 14)
        self.overlay_toggle.hide()

    def _position_overlay_toggle(self) -> None:
        """Center the chevron button just below the jog bar. When the jog
        bar is hidden, pin the chevron near the bottom of the screen
        instead so the user still has a way to bring the controls back."""
        w = self.overlay_toggle.width()
        h = self.overlay_toggle.height()
        x = (self.width() - w) // 2
        if self.jog_bar.isVisible():
            # jog_bar is a top-level window now, so its .y() is a global
            # coord — translate into our local space first.
            jog_local = self.mapFromGlobal(
                QPoint(self.jog_bar.x(), self.jog_bar.y()))
            y = jog_local.y() + self.jog_bar.height() + 6
        else:
            y = self.height() - h - 14
        # Guard against falling off-screen in weird window sizes
        y = max(0, min(y, self.height() - h - 2))
        self._place_overlay(self.overlay_toggle, x, y)
        self.overlay_toggle.raise_()

    # --------------------------------------------------- page arrow overlays --
    def _build_page_arrows(self) -> None:
        """Two semi-transparent chevron buttons anchored to the left and
        right edges of the grid, used to navigate between pages when
        multi-page mode is enabled."""
        arrow_style = (
            "QPushButton {{"
            "  background-color: rgba(0, 0, 0, 160);"
            "  color: white;"
            "  border: none;"
            "  border-radius: {r}px;"
            "  font-size: 28px;"
            "  font-weight: bold;"
            "  padding: 0;"
            "}}"
            "QPushButton:hover {{"
            "  background-color: rgba(43, 95, 161, 210);"
            "}}"
            "QPushButton:pressed {{"
            "  background-color: rgba(36, 82, 139, 230);"
            "}}"
        )
        btn_w, btn_h, radius = 48, 96, 24

        self.prev_page_button = QPushButton("❮", self)  # ❮
        self.prev_page_button.setObjectName("prevPageBtn")
        self.prev_page_button.setFixedSize(btn_w, btn_h)
        self.prev_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_page_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_page_button.setToolTip("Previous page")
        self.prev_page_button.setStyleSheet(
            arrow_style.format(r=radius))
        self._promote_to_overlay_window(self.prev_page_button)
        apply_rounded_mask(self.prev_page_button, radius)
        self.prev_page_button.clicked.connect(
            lambda: self._go_to_page(self.current_page - 1))
        self.prev_page_button.hide()

        self.next_page_button = QPushButton("❯", self)  # ❯
        self.next_page_button.setObjectName("nextPageBtn")
        self.next_page_button.setFixedSize(btn_w, btn_h)
        self.next_page_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_page_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_page_button.setToolTip("Next page")
        self.next_page_button.setStyleSheet(
            arrow_style.format(r=radius))
        self._promote_to_overlay_window(self.next_page_button)
        apply_rounded_mask(self.next_page_button, radius)
        self.next_page_button.clicked.connect(
            lambda: self._go_to_page(self.current_page + 1))
        self.next_page_button.hide()

    def _position_page_arrows(self) -> None:
        """Pin the prev/next arrows to the vertical centre of the window,
        flush with the left and right edges (with a small inset)."""
        inset = 12
        btn_w = self.prev_page_button.width()
        btn_h = self.prev_page_button.height()
        y = (self.height() - btn_h) // 2
        self._place_overlay(self.prev_page_button, inset, y)
        self._place_overlay(
            self.next_page_button, self.width() - btn_w - inset, y)

    def _total_pages(self) -> int:
        """Number of navigable pages given the current fill mode."""
        n = len(self.all_video_files)
        if n == 0:
            return 1
        page_size = self.grid_rows * self.grid_cols
        if self.page_fill == PAGE_FILL_ROUND_UP:
            # Only complete pages; trailing videos that don't fill a page
            # are not shown.
            return max(1, n // page_size)
        else:
            # BLANK and WRAP both show ceil pages.
            return max(1, -(-n // page_size))

    def _page_video_slice(self, page: int) -> list[str]:
        """Return the list of video paths for *page* under the current fill mode."""
        page_size = self.grid_rows * self.grid_cols
        start = page * page_size
        chunk = self.all_video_files[start:start + page_size]

        if self.page_fill == PAGE_FILL_WRAP and 0 < len(chunk) < page_size:
            # Pad by looping from the beginning of the full list.
            shortage = page_size - len(chunk)
            chunk = chunk + self.all_video_files[:shortage]

        # ROUND_UP and BLANK: return chunk as-is (may be short for last page).
        return chunk

    def _update_page_arrows(self) -> None:
        """Show or hide the prev/next arrows based on whether multi-page
        mode is on and how many pages of videos there are."""
        if self.is_playing:
            self.prev_page_button.hide()
            self.next_page_button.hide()
            return

        total_pages = self._total_pages()
        page_size = self.grid_rows * self.grid_cols
        total_pages = max(1, -(-len(self.all_video_files) // page_size))  # ceil

        show_prev = self.multi_page and self.current_page > 0
        show_next = self.multi_page and self.current_page < total_pages - 1

        # Position both buttons first (using current window geometry), then
        # show or hide each one. Showing before positioning caused the button
        # to appear at its default (0,0) location on first display.
        self._position_page_arrows()

        if show_prev:
            self.prev_page_button.show()
            self.prev_page_button.raise_()
        else:
            self.prev_page_button.hide()

        if show_next:
            self.next_page_button.show()
            self.next_page_button.raise_()
        else:
            self.next_page_button.hide()

    def _go_to_page(self, page: int) -> None:
        """Switch the grid to *page* (0-based), reloading thumbnails."""
        total_pages = self._total_pages()
        page_size = self.grid_rows * self.grid_cols
        total_pages = max(1, -(-len(self.all_video_files) // page_size))
        page = max(0, min(page, total_pages - 1))
        if page == self.current_page and self.video_files:
            return

        self.current_page = page
        self.video_files = self._page_video_slice(page)
        start = page * page_size
        self.video_files = self.all_video_files[start:start + page_size]

        self._render_grid()
        self._update_page_arrows()

        # Restart thumbnail and title-translation workers for the new page.
        # Restart the thumbnail worker for the new page's videos
        if self.thumb_worker is not None:
            self.thumb_worker.stop()
            self.thumb_worker.wait(2000)
        self.thumb_worker = ThumbnailWorker(
            list(self.video_files),
            use_sidecar=self.use_sidecar_thumbnails,
            resolution=self.thumbnail_resolution,
        )
        self.thumb_worker.thumbnail_ready.connect(self._on_thumbnail)
        self.thumb_worker.start()
        self._start_title_translation()

    def _build_auto_hide_timer(self) -> None:
        """Single-shot timer that fires 5 seconds after playback begins
        (or after the user reveals the controls) to auto-collapse the
        overlays, when the 'auto-hide controls' option is enabled."""
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.setInterval(5000)
        self.auto_hide_timer.timeout.connect(self._auto_hide_fire)

    def _toggle_overlays(self) -> None:
        if self._overlays_hidden:
            self._reveal_overlays()
            # Give the user a fresh 5-second window before auto-hide
            # takes them away again.
            if self.auto_hide_overlays and self.is_playing:
                self.auto_hide_timer.start()
        else:
            self._hide_overlays()

    def _hide_overlays(self) -> None:
        """Hide the timeline, pause, and Set Thumbnail buttons. Whether
        the close (✕) button is also hidden depends on the
        ``chevron_hides_close_button`` option chosen in the open-folder
        popup. The chevron toggle itself always stays visible so the
        user can bring everything back."""
        if not self.is_playing:
            return
        self._overlays_hidden = True
        self.jog_bar.hide()
        if self.chevron_hides_close_button:
            self.close_button.hide()
        self.set_thumb_button.hide()
        self.loop_button.hide()
        self.overlay_toggle.setText("\u25B4")       # ▴
        self.overlay_toggle.setToolTip(self._tr("show_controls_tip"))
        # Chevron is now on its own at the bottom — reposition accordingly.
        self._position_overlay_toggle()
        self.auto_hide_timer.stop()

    def _reveal_overlays(self) -> None:
        """Restore whatever overlays were visible before _hide_overlays().
        Respects the "Show Set Thumbnail button" preference."""
        self._overlays_hidden = False
        self._position_close_button()
        self.close_button.show()
        self.close_button.raise_()
        if self.show_set_thumb_button:
            self._position_set_thumb_button()
            self.set_thumb_button.show()
            self.set_thumb_button.raise_()
        self._position_loop_button()
        self.loop_button.show()
        self.loop_button.raise_()
        self._position_jog_bar()
        self.jog_bar.show()
        self.jog_bar.raise_()
        self.overlay_toggle.setText("\u25BE")       # ▾
        self.overlay_toggle.setToolTip(self._tr("hide_controls_tip"))
        self._position_overlay_toggle()

    def _auto_hide_fire(self) -> None:
        """5-second timer elapsed — hide overlays unless the user is
        currently scrubbing the timeline (in which case retry later)."""
        if not self.is_playing or self._overlays_hidden:
            return
        if self.timeline.isSliderDown():
            # Don't yank the scrubber out from under the user's cursor.
            self.auto_hide_timer.start()
            return
        self._hide_overlays()

    @staticmethod
    def _format_time(ms: int) -> str:
        if ms is None or ms < 0:
            return "0:00"
        total_s = ms // 1000
        h, rem = divmod(total_s, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _update_position(self) -> None:
        """Poll VLC for current position and refresh the slider/time labels."""
        if not self.is_playing:
            return
        # Don't fight the user while they're dragging the handle
        if self.timeline.isSliderDown():
            return
        length = self.player.get_length()      # ms (0 if unknown yet)
        current = self.player.get_time()       # ms (-1 before playback)
        if length and length > 0 and current is not None and current >= 0:
            ratio = max(0.0, min(1.0, current / length))
            self.timeline.blockSignals(True)
            self.timeline.setValue(int(ratio * 1000))
            self.timeline.blockSignals(False)
            self.time_current.setText(self._format_time(current))
            self.time_total.setText(self._format_time(length))

    def _on_user_seek(self, value: int) -> None:
        """User scrubbed the slider — jump VLC to that position."""
        if not self.is_playing:
            return
        ratio = value / 1000.0
        try:
            self.player.set_position(ratio)
        except Exception:
            pass
        length = self.player.get_length()
        if length and length > 0:
            self.time_current.setText(
                self._format_time(int(length * ratio)))

    def _seek_relative(self, delta_ms: int) -> None:
        """Skip forward/back by `delta_ms` milliseconds."""
        if not self.is_playing:
            return
        length = self.player.get_length()
        current = self.player.get_time()
        if length is None or length <= 0 or current is None or current < 0:
            return
        new_time = max(0, min(length - 100, current + delta_ms))
        try:
            self.player.set_time(int(new_time))
        except Exception:
            pass

    # ----------------------------------------------------- preferences I/O --
    _PREF_KEYS: tuple[tuple[str, type, object], ...] = (
        # (attribute_name, value_type, fallback_default)
        ("show_titles", bool, True),
        ("grid_rows", int, DEFAULT_GRID_ROWS),
        ("grid_cols", int, DEFAULT_GRID_COLS),
        ("full_width", bool, True),
        ("use_sidecar_thumbnails", bool, False),
        ("thumbnail_fit", str, FIT_STRETCH),
        ("show_set_thumb_button", bool, True),
        ("auto_hide_overlays", bool, False),
        ("shuffle_play", bool, False),
        ("thumbnail_resolution", str, DEFAULT_THUMB_RES),
        ("chevron_hides_close_button", bool, True),
        ("multi_page", bool, False),
        ("page_fill", str, PAGE_FILL_ROUND_UP),
        ("translate_titles", bool, False),
        ("last_folder", str, ""),
        ("language", str, "en"),
    )

    def _settings(self) -> "QSettings":
        """QSettings handle bound to the per-user store. Org/app names
        are set in main() so this is the same store across sessions."""
        return QSettings()

    def _tr(self, key: str) -> str:
        """Return the translated string for *key* in the current language."""
        return get_strings(self.language).get(key, key)

    @staticmethod
    def _coerce(value, value_type, fallback):
        """QSettings on some platforms (notably the INI backend) returns
        every value as a string. Coerce booleans / ints / strings back
        into their declared type, falling back if the conversion fails."""
        if value is None:
            return fallback
        if value_type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            try:
                return bool(int(value))
            except (TypeError, ValueError):
                return fallback
        if value_type is int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback
        if value_type is str:
            try:
                return str(value)
            except Exception:
                return fallback
        return value

    def _load_preferences(self) -> None:
        """Read each persisted preference from QSettings into the
        matching MainWindow attribute. Silently uses the in-code default
        if the key is missing or the stored value is unreadable, so the
        first launch (or a corrupted store) still works."""
        try:
            settings = self._settings()
        except Exception as exc:
            print(f"[prefs] could not open settings: {exc}")
            return
        for attr, vtype, fallback in self._PREF_KEYS:
            current = getattr(self, attr, fallback)
            try:
                raw = settings.value(attr, current)
            except Exception:
                raw = current
            value = self._coerce(raw, vtype, current)
            # Sanity check for the resolution key — fall back if a stale
            # store has a name we no longer support.
            if attr == "thumbnail_resolution" and value not in THUMB_RESOLUTIONS:
                value = DEFAULT_THUMB_RES
            if attr == "thumbnail_fit" and value not in (FIT_STRETCH, FIT_CLIP):
                value = FIT_STRETCH
            if attr == "page_fill" and value not in (
                    PAGE_FILL_BLANK, PAGE_FILL_ROUND_UP, PAGE_FILL_WRAP):
                value = PAGE_FILL_ROUND_UP
            if attr in ("grid_rows", "grid_cols"):
                value = max(1, min(MAX_GRID_DIM, int(value)))
            setattr(self, attr, value)

    def _save_preferences(self) -> None:
        """Persist every tracked preference back to QSettings. Called
        whenever the open-folder dialog is accepted, and one last time
        on app close so an unexpectedly-quit session still writes its
        last state."""
        try:
            settings = self._settings()
        except Exception as exc:
            print(f"[prefs] could not open settings: {exc}")
            return
        for attr, _vtype, _fallback in self._PREF_KEYS:
            try:
                settings.setValue(attr, getattr(self, attr))
            except Exception as exc:
                print(f"[prefs] could not save {attr}: {exc}")
        try:
            settings.sync()
        except Exception:
            pass

    # ------------------------------------------------------- folder loading --
    def _show_open_dialog(self) -> None:
        dlg = OpenFolderDialog(
            self,
            show_titles_default=self.show_titles,
            rows_default=self.grid_rows,
            cols_default=self.grid_cols,
            full_width_default=self.full_width,
            use_sidecar_default=self.use_sidecar_thumbnails,
            thumbnail_fit_default=self.thumbnail_fit,
            show_set_thumb_default=self.show_set_thumb_button,
            auto_hide_default=self.auto_hide_overlays,
            shuffle_default=self.shuffle_play,
            multi_page_default=self.multi_page,
            page_fill_default=self.page_fill,
            thumbnail_resolution_default=self.thumbnail_resolution,
            chevron_hides_close_default=self.chevron_hides_close_button,
            last_folder_default=self.last_folder,
            language_default=self.language,
            translate_titles_default=self.translate_titles,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen_folder:
            self.show_titles = dlg.show_titles
            self.grid_rows = dlg.grid_rows
            self.grid_cols = dlg.grid_cols
            self.full_width = dlg.full_width
            self.use_sidecar_thumbnails = dlg.use_sidecar
            self.thumbnail_fit = dlg.thumbnail_fit
            self.show_set_thumb_button = dlg.show_set_thumb_button
            self.auto_hide_overlays = dlg.auto_hide_overlays
            self.shuffle_play = dlg.shuffle_play
            self.multi_page = dlg.multi_page
            self.page_fill = dlg.page_fill
            self.translate_titles = dlg.translate_titles
            self.thumbnail_resolution = dlg.thumbnail_resolution
            self.chevron_hides_close_button = dlg.chevron_hides_close_button
            self.language = dlg.language
            self._retranslate_menu()
            # Persist these choices so the next run remembers them.
            self._save_preferences()
            self._load_folder(dlg.chosen_folder)

    def _load_folder(self, folder: str) -> None:
        try:
            entries = sorted(os.listdir(folder))
        except OSError as exc:
            QMessageBox.critical(
                self, self._tr("folder_error_title"),
                self._tr("folder_error_msg").format(error=exc))
            return

        videos = [
            os.path.join(folder, n)
            for n in entries
            if n.lower().endswith(VIDEO_EXTS)
            and os.path.isfile(os.path.join(folder, n))
        ]
        if not videos:
            QMessageBox.warning(
                self, self._tr("no_videos_title"),
                self._tr("no_videos_msg").format(exts=", ".join(VIDEO_EXTS)))
            return

        self.all_video_files = videos
        self.current_page = 0
        self.video_files = self._page_video_slice(0)
        page_size = self.grid_rows * self.grid_cols
        if self.multi_page:
            self.video_files = videos[:page_size]
        else:
            self.video_files = videos[:page_size]
        self.thumbnails.clear()
        self._render_grid()
        QTimer.singleShot(0, self._update_page_arrows)

        # Remember this folder so the next run's "Open Last Folder"
        # button can jump straight back to it.
        try:
            self.last_folder = os.path.abspath(folder)
            self._save_preferences()
        except Exception as exc:
            print(f"[prefs] could not save last_folder: {exc}")

        # Swap in a new thumbnail worker (stops any previous one first)
        if self.thumb_worker is not None:
            self.thumb_worker.stop()
            self.thumb_worker.wait(2000)
        self.thumb_worker = ThumbnailWorker(
            list(self.video_files),
            use_sidecar=self.use_sidecar_thumbnails,
            resolution=self.thumbnail_resolution,
        )
        self.thumb_worker.thumbnail_ready.connect(self._on_thumbnail)
        self.thumb_worker.start()

        self._start_title_translation()

    def _start_title_translation(self) -> None:
        """Kick off a background worker to translate the current page's
        video titles if the option is enabled and a non-English language
        is selected. Stops any previously running translation worker first."""
        if self.title_worker is not None:
            self.title_worker.stop()
            self.title_worker.wait(1000)
            self.title_worker = None

        if not self.translate_titles:
            return
        if self.language == "en":
            return

        titles = []
        for idx, entry in enumerate(self.cell_widgets):
            if entry is not None:
                raw = entry["title"].property("fullText") or ""
                titles.append((idx, str(raw)))

        if not titles:
            return

        self.title_worker = TitleTranslatorWorker(titles, self.language)
        self.title_worker.title_ready.connect(self._on_title_translated)
        self.title_worker.start()

    def _on_title_translated(self, idx: int, text: str) -> None:
        if idx >= len(self.cell_widgets) or self.cell_widgets[idx] is None:
            return
        self._set_title_text(self.cell_widgets[idx]["title"], text)

    def _on_thumbnail(self, idx: int, path: str, qimg: QImage) -> None:
        if idx >= len(self.video_files) or self.video_files[idx] != path:
            return
        if idx >= len(self.cell_widgets) or self.cell_widgets[idx] is None:
            return
        pixmap = QPixmap.fromImage(qimg)
        self.thumbnails[path] = pixmap
        widgets = self.cell_widgets[idx]
        widgets["thumb"].setPixmap(pixmap)
        widgets["thumb"].setText("")

    # ----------------------------------------------------------- grid view --
    def _render_grid(self) -> None:
        self.stack.setCurrentWidget(self.grid_page)

        # Clear existing widgets
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.cell_widgets = []

        # Outer margin and gap between cells depend on the layout mode.
        if self.full_width:
            self.grid_layout.setContentsMargins(0, 0, 0, 0)
            self.grid_layout.setSpacing(0)
        else:
            self.grid_layout.setContentsMargins(14, 14, 14, 14)
            self.grid_layout.setSpacing(12)

        # Set stretches for the currently-configured grid size, and clear
        # any stretches left over from a previously-larger grid.
        for r in range(MAX_GRID_DIM):
            self.grid_layout.setRowStretch(r, 1 if r < self.grid_rows else 0)
        for c in range(MAX_GRID_DIM):
            self.grid_layout.setColumnStretch(
                c, 1 if c < self.grid_cols else 0)

        num_slots = self.grid_rows * self.grid_cols
        for idx in range(num_slots):
            r, c = divmod(idx, self.grid_cols)
            if idx < len(self.video_files):
                path = self.video_files[idx]
                entry = self._make_video_cell(path, idx + 1)
                self.grid_layout.addWidget(entry["cell"], r, c)
                self.cell_widgets.append(entry)
                cached = self.thumbnails.get(path)
                if cached is not None:
                    entry["thumb"].setPixmap(cached)
                    entry["thumb"].setText("")
            else:
                cell = self._make_empty_cell()
                self.grid_layout.addWidget(cell, r, c)
                self.cell_widgets.append(None)

    def _make_video_cell(self, path: str, number: int) -> dict:
        # Strip the extension from the display name (e.g. "Name.mp4" -> "Name")
        display_name = os.path.splitext(os.path.basename(path))[0]
        cell = ClickableCell()

        # In full-width mode, strip the cell's border / rounded corners so
        # neighboring cells sit flush against each other with no visible gap.
        if self.full_width:
            cell.setStyleSheet(
                "#videoCell { background: #000000; border: none; "
                "             border-radius: 0px; }"
                "#videoCell:hover { background: #000000; "
                "                   border: none; }"
            )

        layout = QVBoxLayout(cell)
        if self.full_width:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        else:
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

        # ThumbnailLabel renders the pixmap in either FIT_STRETCH (distort
        # to fill) or FIT_CLIP (keep aspect ratio, clip to fill) — the
        # mode is chosen by the user in the open-folder popup.
        thumb = ThumbnailLabel()
        thumb.setText("Loading thumbnail…")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.set_fit_mode(self.thumbnail_fit)
        if self.full_width:
            thumb.setMinimumSize(1, 1)
        else:
            thumb.setMinimumSize(THUMB_MIN_W, THUMB_MIN_H)
        thumb.setStyleSheet(
            "background: black; color: #777777; "
            "font-size: 11px; border: none;")
        layout.addWidget(thumb, 1)

        # All titles share the same height so the grid looks uniform even
        # when filenames have very different lengths. Word-wrap is off and
        # long names are elided with "…" (handled in _set_title_text).
        title = QLabel()
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(False)
        title.setFixedHeight(TITLE_BAR_HEIGHT)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setProperty("fullText", display_name)
        if self.full_width:
            # In full-width mode, float the title over the thumbnail with a
            # subtle background so it's legible without adding a gap between
            # neighboring videos.
            title.setStyleSheet(
                "color: white; font-size: 12px; font-weight: bold; "
                "background: rgba(0, 0, 0, 140); padding: 4px 8px; "
                "border: none;")
            title.setParent(cell)
            title.raise_()
            # Positioning is handled by _place_floating_title() on resize /
            # after layout so the overlay stays pinned to the bottom of
            # each cell.
        else:
            title.setStyleSheet(
                "color: white; font-size: 12px; font-weight: bold; "
                "border: none;")
            layout.addWidget(title)
        self._set_title_text(title, display_name)
        if not self.show_titles:
            title.hide()

        cell.clicked.connect(lambda p=path: self._play_video(p))

        # Install an event filter so we can reposition the floating title
        # overlay (full-width mode) or re-elide the inline title text
        # (normal mode) whenever the cell is resized.
        cell.installEventFilter(self)

        return {"cell": cell, "thumb": thumb, "title": title}

    def eventFilter(self, obj, event):
        """On cell resize: reposition floating titles in full-width mode,
        and re-elide inline titles in normal mode, so long filenames never
        overflow and all title bars keep a consistent height."""
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            for entry in self.cell_widgets:
                if entry is None:
                    continue
                if entry["cell"] is obj:
                    if self.full_width:
                        self._place_floating_title(entry)
                    else:
                        title = entry["title"]
                        full = title.property("fullText") or title.text()
                        self._set_title_text(title, str(full))
                    break
        return super().eventFilter(obj, event)

    def _place_floating_title(self, entry: dict) -> None:
        cell = entry["cell"]
        title = entry["title"]
        if title is None or title.parent() is not cell:
            return
        # Span the bottom of the cell at a fixed height so every title bar
        # in the grid is the same size.
        h = min(TITLE_BAR_HEIGHT, cell.height())
        title.setGeometry(0, cell.height() - h, cell.width(), h)
        title.raise_()
        # Re-elide the text to the new width so long filenames don't
        # overflow the cell.
        full = title.property("fullText") or title.text()
        self._set_title_text(title, str(full))

    @staticmethod
    def _set_title_text(label: "QLabel", text: str) -> None:
        """Set label text, eliding with "…" if it doesn't fit the label's
        current width. Called both when the cell is created and whenever
        the cell is resized."""
        label.setProperty("fullText", text)
        fm = label.fontMetrics()
        # Leave a little breathing room for the label's padding.
        avail = max(1, label.width() - 16)
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail)
        label.setText(elided)

    def _make_empty_cell(self) -> QFrame:
        cell = QFrame()
        if self.full_width:
            cell.setStyleSheet(
                "QFrame { background: #000000; border: none; "
                "         border-radius: 0px; }")
        else:
            cell.setStyleSheet(
                "QFrame { background: #151515; border: 1px solid #222222; "
                "         border-radius: 6px; }")
        layout = QVBoxLayout(cell)
        if self.full_width:
            layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("(empty slot)")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: #555555; font-style: italic; border: none;")
        layout.addWidget(lbl)
        return cell

    # -------------------------------------------------------------- playback --
    def _play_video(self, path: str) -> None:
        if self.is_playing:
            return
        self.is_playing = True
        self.current_video_path = path
        try:
            self.current_video_idx = self.video_files.index(path)
        except ValueError:
            self.current_video_idx = None

        # Remember what the main window's display state was before we
        # force-fullscreen it for playback, so we can restore it on stop
        # instead of dropping the user out of fullscreen if that's where
        # they already were.
        self._was_fullscreen_before_play = self.isFullScreen()
        self._was_maximized_before_play = self.isMaximized()

        # Switch to the video page so the surface is laid out & visible,
        # then go fullscreen, then give Qt one event-loop tick so the
        # native surface is definitely realized before handing its
        # handle to VLC.
        self.stack.setCurrentWidget(self.video_page)
        if not self._was_fullscreen_before_play:
            self.showFullScreen()

        # Re-assert sharp corners + black DWM border after the fullscreen
        # transition; Windows can reset these on state change, and we
        # don't want rounded-corner gaps flashing at the screen edges.
        QTimer.singleShot(0, self._paint_main_window_border_black)
        QTimer.singleShot(120, self._paint_main_window_border_black)

        QTimer.singleShot(60, lambda: self._begin_vlc_playback(path))

    def _begin_vlc_playback(self, path: str) -> None:
        if not self.is_playing:
            return
        handle = int(self.video_surface.winId())
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(handle)
        elif sys.platform == "win32":
            self.player.set_hwnd(handle)
        elif sys.platform == "darwin":
            # PyQt6's winId() on macOS returns a valid NSView* pointer,
            # which is exactly what libvlc's set_nsobject expects.
            self.player.set_nsobject(handle)

        # Stop VLC from grabbing mouse/keyboard input on the video surface.
        # Without this, on Windows the video window eats clicks that were
        # aimed at our overlay controls, so buttons appear "stuck behind".
        try:
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)
        except Exception:
            pass

        media = self.vlc_instance.media_new(path)
        self.player.set_media(media)
        self.player.play()

        # Show the floating close button and the transport bar on top
        # of the video.
        self._position_close_button()
        self.close_button.show()
        self.prev_page_button.hide()
        self.next_page_button.hide()

        # Reset the "Set Thumbnail" button label in case it was showing
        # the "✓ Thumbnail Set" confirmation from a previous play, then
        # show it to the left of the ✕ button — but only if the user has
        # the "Show Set Thumbnail button" option enabled in the popup.
        self.set_thumb_button.setIcon(_make_camera_icon(26))
        if self.show_set_thumb_button:
            self._position_set_thumb_button()
            self.set_thumb_button.show()
        else:
            self.set_thumb_button.hide()

        # Show the loop button to the left of the camera button.
        self._position_loop_button()
        self.loop_button.show()

        # Reset and reveal the jog/transport bar
        self.timeline.blockSignals(True)
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        self.time_current.setText("0:00")
        self.time_total.setText("0:00")
        self._set_pause_button_state(paused=False)
        self._position_jog_bar()
        self.jog_bar.show()
        self.position_timer.start()

        # Controls are visible at the start of each playback; reset the
        # chevron to its "press to hide" state and show it under the bar.
        self._overlays_hidden = False
        self.overlay_toggle.setText("\u25BE")     # ▾
        self.overlay_toggle.setToolTip(self._tr("hide_controls_tip"))
        self._position_overlay_toggle()
        self.overlay_toggle.show()

        # Raise all overlays above the video surface. On Windows VLC may
        # briefly take the top of the child z-order when its rendering
        # surface is created, so we also schedule a few deferred re-raises
        # covering the first ~1s of playback as a safety net.
        self._raise_all_overlays()
        for delay in (50, 150, 350, 700, 1200):
            QTimer.singleShot(delay, self._raise_all_overlays)

        # If the user asked for auto-hide, start the 5-second countdown.
        if self.auto_hide_overlays:
            self.auto_hide_timer.start()

    def _raise_all_overlays(self) -> None:
        """Bring every overlay widget above the video surface in native
        window z-order. Used on every play-start and also from the VLC
        'Playing' event, because on Windows the VLC surface can take the
        top of the z-order mid-initialization and hide our controls.

        Also strips the native Windows client-edge style off each overlay
        (a no-op on macOS/Linux), which removes the thin gray border
        that Windows would otherwise draw around a top-level Tool
        window. Idempotent — fine to call repeatedly.
        """
        if not self.is_playing:
            return
        for widget_attr, visibility_guard in (
            ("close_button", lambda: True),
            ("set_thumb_button", lambda: self.show_set_thumb_button
                and not self._overlays_hidden),
            ("jog_bar", lambda: not self._overlays_hidden),
            ("overlay_toggle", lambda: True),
        ):
            w = getattr(self, widget_attr, None)
            if w is None or not w.isVisible():
                continue
            if not visibility_guard():
                continue
            try:
                w.raise_()
            except Exception:
                pass
            self._strip_native_window_border(w)

    def _capture_current_frame_as_thumbnail(self) -> None:
        """Snapshot whatever VLC is currently showing and use it as the
        grid thumbnail for the video being played. The PNG is cached in
        a per-user directory keyed on the video's absolute path, so the
        custom thumbnail is still there next time this folder is opened.
        """
        if not self.is_playing or self.current_video_path is None:
            return

        # Make sure the cache dir exists before we write into it.
        cache_dir = _cache_dir()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self, "Set Thumbnail",
                f"Couldn't create thumbnail cache directory:\n{exc}")
            return

        # Have VLC write the current frame to a temp PNG. Using a temp
        # file first avoids leaving a half-written cache entry behind if
        # anything goes wrong mid-write; we move it into place on success.
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".png", prefix="vgp_snap_")
        os.close(tmp_fd)
        rc = -1
        try:
            rc = self.player.video_take_snapshot(0, tmp_path, 0, 0)
        except Exception as exc:
            print(f"[snapshot] VLC error: {exc}")

        if rc != 0 or (not os.path.isfile(tmp_path)
                       or os.path.getsize(tmp_path) == 0):
            # Snapshot failed (VLC not ready, video output not available,
            # etc.). Clean up the empty temp file and bail out.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            QMessageBox.warning(
                self, "Set Thumbnail",
                "Couldn't capture the current frame. "
                "Try again a moment after playback begins.")
            return

        # Load the snapshot, letterbox it to our standard thumb size,
        # and persist it to the cache as <sha1(path)>.png.
        thumb_qimg = load_image_as_thumb_qimage(
            tmp_path, self.thumbnail_resolution)
        dest = _cached_thumb_path(self.current_video_path)
        try:
            os.replace(tmp_path, dest)
        except OSError as exc:
            print(f"[snapshot] could not move to cache: {exc}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if thumb_qimg is None:
            return

        # Update the live grid cell so the new thumbnail appears as soon
        # as the user returns to the grid.
        pixmap = QPixmap.fromImage(thumb_qimg)
        self.thumbnails[self.current_video_path] = pixmap
        idx = self.current_video_idx
        if (idx is not None and 0 <= idx < len(self.cell_widgets)
                and self.cell_widgets[idx] is not None):
            entry = self.cell_widgets[idx]
            entry["thumb"].setPixmap(pixmap)
            entry["thumb"].setText("")

        # Brief on-screen confirmation so the user knows it worked.
        self.set_thumb_button.setIcon(_make_checkmark_icon(26))
        QTimer.singleShot(
            1400,
            lambda: self.set_thumb_button.setIcon(_make_camera_icon(26)))

    def _toggle_pause(self) -> None:
        """Toggle VLC's paused state and refresh the button label."""
        if not self.is_playing:
            return
        try:
            self.player.pause()      # libvlc's pause() is a toggle
        except Exception:
            pass
        # Optimistically flip the label right away so the button feels
        # responsive. The VLC Paused/Playing events will fire shortly
        # after and confirm (or correct) the state.
        if self.pause_button.text() == "\u23F8":
            self._set_pause_button_state(paused=True)
        else:
            self._set_pause_button_state(paused=False)

    def _set_pause_button_state(self, paused: bool) -> None:
        if paused:
            self.pause_button.setText("\u25B6")        # ▶
            self.pause_button.setToolTip("Resume (Space)")
        else:
            self.pause_button.setText("\u23F8")        # ⏸
            self.pause_button.setToolTip("Pause (Space)")

    def _on_vlc_paused(self, _event) -> None:
        # VLC events fire on VLC's thread — bounce back to the GUI thread.
        QTimer.singleShot(
            0, lambda: self._set_pause_button_state(paused=True))

    def _on_vlc_playing(self, _event) -> None:
        # Fires on VLC's thread. Bounce to the GUI thread and, as well as
        # syncing the pause button, re-raise our overlays — VLC's first
        # frame on Windows often pushes its rendering surface to the top
        # of the child z-order and would otherwise hide the controls.
        def _on_gui_thread() -> None:
            self._set_pause_button_state(paused=False)
            self._raise_all_overlays()
        QTimer.singleShot(0, _on_gui_thread)

    def _on_vlc_end(self, _event) -> None:
        # Fires on VLC's thread — defer UI updates to the Qt main loop
        QTimer.singleShot(80, self._handle_video_ended)

    def _handle_video_ended(self) -> None:
        """Called on the GUI thread when the currently-playing video ends
        (or errors out). Loops the current video if loop mode is active,
        shuffles to a new video if shuffle is enabled, otherwise returns
        to the grid."""
        if self.loop_active and self.is_playing and self.current_video_path:
            path = self.current_video_path
            media = self.vlc_instance.media_new(path)
            self.player.set_media(media)
            self.player.play()
        elif (self.shuffle_play
                and self.is_playing
                and len(self.video_files) >= 1):
            self._play_next_shuffled()
        else:
            self._stop_playback()

    def _play_next_shuffled(self) -> None:
        """Pick a random video from the loaded list (avoiding the one that
        just finished if we have more than one) and start it without
        returning to the grid. Preserves the current hide/show state of
        the overlays so a shuffle session can stay "clean" if the user
        has collapsed the controls."""
        current = self.current_video_path
        choices = [v for v in self.video_files if v != current]
        if not choices:
            choices = list(self.video_files)
        if not choices:
            self._stop_playback()
            return

        next_path = random.choice(choices)
        was_hidden = self._overlays_hidden

        # Tear down timers / VLC state tied to the outgoing video, but
        # keep is_playing=True and stay on the video page / fullscreen.
        self.position_timer.stop()
        self.auto_hide_timer.stop()
        self._stop_vlc_player()

        self.current_video_path = next_path
        try:
            self.current_video_idx = self.video_files.index(next_path)
        except ValueError:
            self.current_video_idx = None

        # Kick off the new video through the same path as a fresh play.
        QTimer.singleShot(
            60, lambda p=next_path: self._begin_vlc_playback(p))
        # _begin_vlc_playback unconditionally re-shows the overlays;
        # if the user had them collapsed, re-hide after things settle.
        if was_hidden:
            QTimer.singleShot(140, self._hide_overlays)

    def _stop_vlc_player(self) -> None:
        """Stop the VLC player safely.

        Before calling stop() we detach the native render surface by
        passing a null handle. This gives VLC a clean signal to release
        its renderer and avoids a class of Windows hangs where the vout
        module blocks trying to clip a DWM taskbar thumbnail against a
        disappearing HWND (the old ``SetThumbNailClip 0x800706f4``
        symptom with the d3d11 output). Harmless on macOS/Linux.
        """
        try:
            if sys.platform == "win32":
                self.player.set_hwnd(0)
            elif sys.platform.startswith("linux"):
                self.player.set_xwindow(0)
            elif sys.platform == "darwin":
                self.player.set_nsobject(0)
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass

    def _stop_playback(self) -> None:
        if not self.is_playing:
            return
        self.is_playing = False
        self.position_timer.stop()
        self.auto_hide_timer.stop()
        self.close_button.hide()
        self.set_thumb_button.hide()
        self.loop_button.hide()
        self.jog_bar.hide()
        self.overlay_toggle.hide()
        self._overlays_hidden = False
        self._stop_vlc_player()
        self.current_video_path = None
        self.current_video_idx = None
        # Restore whichever window state we had before playback began.
        # If the user was already in fullscreen before playing a video,
        # we stay in fullscreen rather than yanking them out of it.
        if getattr(self, "_was_fullscreen_before_play", False):
            # Already fullscreen from _play_video_at (or from earlier);
            # don't touch the window state.
            pass
        elif getattr(self, "_was_maximized_before_play", False):
            self.showMaximized()
        else:
            self.showNormal()
        # Keep the File menu's Full Screen toggle in sync.
        if getattr(self, "fullscreen_act", None) is not None:
            self.fullscreen_act.setChecked(self.isFullScreen())
        self.stack.setCurrentWidget(self.grid_page)
        self._update_page_arrows()

    # -------------------------------------------------------------- keyboard --
    def keyPressEvent(self, event):
        key = event.key()
        if self.is_playing and key == Qt.Key.Key_Escape:
            self._stop_playback()
        elif self.is_playing and key == Qt.Key.Key_Space:
            self._toggle_pause()
        elif self.is_playing and key == Qt.Key.Key_Left:
            self._seek_relative(-5000)        # back 5 seconds
        elif self.is_playing and key == Qt.Key.Key_Right:
            self._seek_relative(+5000)        # forward 5 seconds
        elif (not self.is_playing and self.multi_page
              and key == Qt.Key.Key_Left):
            self._go_to_page(self.current_page - 1)
        elif (not self.is_playing and self.multi_page
              and key == Qt.Key.Key_Right):
            self._go_to_page(self.current_page + 1)
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------------- resize --
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_visible_overlays()

    def moveEvent(self, event):
        # Overlays are top-level windows positioned in global coords, so
        # they need to be re-placed whenever the main window moves (e.g.
        # the user drags the title bar or the window goes full-screen).
        super().moveEvent(event)
        self._reposition_visible_overlays()

    def _reposition_visible_overlays(self) -> None:
        """Re-run each overlay's positioning function if that overlay is
        currently visible. Used by resizeEvent and moveEvent to keep the
        top-level overlay windows pinned to their place over the main
        window as it resizes or moves."""
        if getattr(self, "close_button", None) is not None \
                and self.close_button.isVisible():
            self._position_close_button()
        if getattr(self, "set_thumb_button", None) is not None \
                and self.set_thumb_button.isVisible():
            self._position_set_thumb_button()
        if getattr(self, "loop_button", None) is not None \
                and self.loop_button.isVisible():
            self._position_loop_button()
        if getattr(self, "jog_bar", None) is not None \
                and self.jog_bar.isVisible():
            self._position_jog_bar()
        if getattr(self, "overlay_toggle", None) is not None \
                and self.overlay_toggle.isVisible():
            self._position_overlay_toggle()
        if getattr(self, "prev_page_button", None) is not None:
            self._position_page_arrows()

    # ------------------------------------------------------------------ misc --
    def _toggle_fullscreen(self, checked: bool | None = None) -> None:
        """Toggle the main window between full-screen and normal.

        Note: this toggles the OS-level full-screen state of the *main
        window* (i.e. the frame / menu bar / title bar are hidden) and
        is independent of the in-app "play this video fullscreen inside
        the grid window" behavior.
        """
        if self.isFullScreen():
            # Return to whichever pre-fullscreen state we had. showNormal()
            # handles both maximized and ordinary windows correctly on all
            # three platforms.
            self.showNormal()
        else:
            self.showFullScreen()
        # Keep the menu check in sync with the actual window state.
        if getattr(self, "fullscreen_act", None) is not None:
            self.fullscreen_act.setChecked(self.isFullScreen())

    def showEvent(self, event):
        # The main window's HWND exists by the time showEvent fires, so
        # this is the first safe moment to ask DWM to paint the 1px
        # accent border black. Re-applied on state changes below because
        # Windows may repaint/reset attributes when the window enters
        # or leaves fullscreen.
        super().showEvent(event)
        self._paint_main_window_border_black()

    def changeEvent(self, event):
        # The user can leave fullscreen via the OS (e.g. Esc on some
        # desktops, window manager shortcut, Mission Control, etc.). Keep
        # our menu toggle honest by mirroring the real window state, and
        # nudge the top-level overlay windows to re-pin themselves over
        # the (possibly just-resized) main window.
        if event.type() == QEvent.Type.WindowStateChange:
            if getattr(self, "fullscreen_act", None) is not None:
                self.fullscreen_act.setChecked(self.isFullScreen())
            # Defer the reposition by one event-loop tick so the main
            # window's geometry has settled into its new state, and
            # re-assert the black DWM border in case Windows reset it
            # when transitioning into/out of fullscreen.
            QTimer.singleShot(0, self._reposition_visible_overlays)
            QTimer.singleShot(0, self._paint_main_window_border_black)
        super().changeEvent(event)

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About Video Grid Player",
            "Video Grid Player\n\n"
            "Displays your videos in a configurable grid (up to 6×6) with "
            "thumbnails. Click a cell to play the video fullscreen inside "
            "the app.\n\n"
            "Controls while playing:\n"
            "  • Esc            return to grid (or click the ✕ button)\n"
            "  • Space          pause / resume\n"
            "  • ← / →          skip 5 seconds back / forward\n"
            "  • Click / drag   on the bottom timeline to scrub\n"
            "  • Set Thumbnail  capture the current frame as this "
            "video's grid thumbnail\n\n"
            "Built with Python, PyQt6, python-vlc, and OpenCV.")

    def closeEvent(self, event):
        # Final save on quit catches any state that changed without the
        # open-folder dialog being touched (defensive — most settings
        # changes already round-trip through that dialog).
        try:
            self._save_preferences()
        except Exception:
            pass
        if self.thumb_worker is not None:
            self.thumb_worker.stop()
            self.thumb_worker.wait(2000)
        if self.title_worker is not None:
            self.title_worker.stop()
            self.title_worker.wait(1000)
        # Use the safe stop path that detaches the render HWND first,
        # then release the player / instance. Without the HWND detach,
        # VLC can hang on app-exit with the d3d11 vout bug.
        self._stop_vlc_player()
        try:
            self.player.release()
            self.vlc_instance.release()
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # Use the OS's exact DPI scale factor (e.g. 1.25, 1.5) instead of
    # rounding it to the nearest integer. Without this, on Windows
    # displays scaled to 125% / 150% the QPaintDevice's
    # devicePixelRatio reads as 1.0 even though the OS is asking for
    # 1.5 — which leaves bitmaps (like our thumbnails) under-resolved
    # and visibly soft. Must be set before QApplication is constructed.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    # Set application identity so QSettings picks a stable per-user
    # storage location (registry on Windows, plist on macOS, INI under
    # ~/.config on Linux). Required for the saved-preferences feature.
    app.setOrganizationName("VideoGridPlayer")
    app.setApplicationName("VideoGridPlayer")
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    window = VideoGridApp(initial_folder=initial)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
