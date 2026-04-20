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
import sys
import tempfile
from pathlib import Path

# ---- dependency checks ----------------------------------------------------
_missing: list[str] = []
try:
    from PyQt6.QtCore import Qt, QEvent, QRectF, QTimer, QThread, pyqtSignal
    from PyQt6.QtGui import (
        QAction, QColor, QImage, QKeySequence, QPainter, QPainterPath,
        QPalette, QPixmap, QRegion,
    )
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QDialog, QFileDialog, QFrame,
        QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
        QPushButton, QSlider, QSpinBox, QStackedWidget, QVBoxLayout,
        QWidget,
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

THUMB_W = 320
THUMB_H = 180

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
def _fit_rgb_to_qimage(rgb: "np.ndarray") -> "QImage":
    """Scale an RGB numpy image to fit within THUMB_W x THUMB_H while
    preserving aspect ratio, and return a QImage of exactly the scaled
    size (no letterbox / padding). The display widget decides later
    whether to stretch this to fill the cell or to scale-and-clip it."""
    h, w = rgb.shape[:2]
    scale = min(THUMB_W / w, THUMB_H / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    # tobytes() gives us a detached buffer so the returned QImage is safe
    # to keep around after the numpy array is freed.
    return QImage(
        resized.tobytes(), new_w, new_h, new_w * 3,
        QImage.Format.Format_RGB888,
    ).copy()


def extract_thumbnail(path: str) -> "QImage | None":
    """Grab a representative frame from a video and return it as a
    letterboxed QImage of size (THUMB_W x THUMB_H)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Skip a bit into the file to avoid black intros / studio logos
        if total > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES,
                    max(1, min(total // 10, total - 1)))
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
    finally:
        cap.release()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return _fit_rgb_to_qimage(rgb)


def load_image_as_thumb_qimage(path: str) -> "QImage | None":
    """Load an arbitrary image file (jpg/png/webp/bmp/...) and return a
    QImage scaled to fit within THUMB_W x THUMB_H while preserving aspect
    ratio. No padding is added — the display widget is responsible for
    deciding whether to stretch or clip the image inside its cell."""
    src = QImage(path)
    if src.isNull():
        return None
    src = src.convertToFormat(QImage.Format.Format_RGB888)
    return src.scaled(
        THUMB_W, THUMB_H,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def load_thumbnail_for_video(
    path: str, use_sidecar: bool
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
        img = load_image_as_thumb_qimage(str(cached))
        if img is not None:
            return img
    if use_sidecar:
        sidecar = _find_sidecar_image(path)
        if sidecar is not None:
            img = load_image_as_thumb_qimage(sidecar)
            if img is not None:
                return img
    return extract_thumbnail(path)


class ThumbnailWorker(QThread):
    """Resolve thumbnails for a list of paths off the GUI thread.

    For each video we first check the user-set cache, then (optionally) a
    matching sidecar image, then fall back to decoding a frame from the
    video itself."""
    thumbnail_ready = pyqtSignal(int, str, QImage)

    def __init__(self, paths: list[str], use_sidecar: bool = False):
        super().__init__()
        self._paths = paths
        self._use_sidecar = use_sidecar
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        for idx, path in enumerate(self._paths):
            if self._stop:
                return
            try:
                img = load_thumbnail_for_video(path, self._use_sidecar)
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
        scaled = self._src_pixmap.scaled(
            self.size(),
            aspect,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
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
                 auto_hide_default: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Open Videos")
        self.setFixedSize(620, 600)
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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)

        title = QLabel("Video Grid Player")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: white; font-size: 18px; font-weight: bold;")
        root.addWidget(title)

        desc = QLabel(
            "Select a folder containing your video files.\n"
            "Your videos will be shown in the grid configured below.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #bbbbbb;")
        root.addWidget(desc)

        root.addSpacing(18)

        # --- grid size controls ------------------------------------------
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
        label_style = (
            "color: #dddddd; font-size: 12px; background: transparent;"
        )

        grid_row = QHBoxLayout()
        grid_row.addStretch(1)

        rows_label = QLabel("Rows:")
        rows_label.setStyleSheet(label_style)
        grid_row.addWidget(rows_label)

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, MAX_GRID_DIM)
        self.rows_spin.setValue(rows_default)
        self.rows_spin.setStyleSheet(spin_style)
        grid_row.addWidget(self.rows_spin)

        grid_row.addSpacing(24)

        cols_label = QLabel("Columns:")
        cols_label.setStyleSheet(label_style)
        grid_row.addWidget(cols_label)

        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, MAX_GRID_DIM)
        self.cols_spin.setValue(cols_default)
        self.cols_spin.setStyleSheet(spin_style)
        grid_row.addWidget(self.cols_spin)

        grid_row.addStretch(1)
        root.addLayout(grid_row)

        root.addSpacing(14)

        # --- options ------------------------------------------------------
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

        self.titles_checkbox = QCheckBox("Show video titles in the grid")
        self.titles_checkbox.setChecked(show_titles_default)
        self.titles_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.titles_checkbox.setStyleSheet(check_style)
        root.addWidget(self.titles_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(8)

        self.full_width_checkbox = QCheckBox(
            "Full-width layout (no gaps between videos)")
        self.full_width_checkbox.setChecked(full_width_default)
        self.full_width_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full_width_checkbox.setStyleSheet(check_style)
        root.addWidget(self.full_width_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(8)

        self.sidecar_checkbox = QCheckBox(
            "Use matching image files as thumbnails "
            "(e.g. video.jpg next to video.mp4)")
        self.sidecar_checkbox.setChecked(use_sidecar_default)
        self.sidecar_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidecar_checkbox.setStyleSheet(check_style)
        root.addWidget(self.sidecar_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(8)

        self.clip_thumb_checkbox = QCheckBox(
            "Preserve thumbnail aspect ratio "
            "(clip to fit instead of stretching)")
        self.clip_thumb_checkbox.setChecked(
            thumbnail_fit_default == FIT_CLIP)
        self.clip_thumb_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clip_thumb_checkbox.setStyleSheet(check_style)
        root.addWidget(self.clip_thumb_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(8)

        self.set_thumb_button_checkbox = QCheckBox(
            "Show \u201cSet Thumbnail\u201d button while a video is playing")
        self.set_thumb_button_checkbox.setChecked(show_set_thumb_default)
        self.set_thumb_button_checkbox.setCursor(
            Qt.CursorShape.PointingHandCursor)
        self.set_thumb_button_checkbox.setStyleSheet(check_style)
        root.addWidget(self.set_thumb_button_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addSpacing(8)

        self.auto_hide_checkbox = QCheckBox(
            "Auto-hide on-screen controls after 5 seconds of playback")
        self.auto_hide_checkbox.setChecked(auto_hide_default)
        self.auto_hide_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_hide_checkbox.setStyleSheet(check_style)
        root.addWidget(self.auto_hide_checkbox, 0,
                       Qt.AlignmentFlag.AlignHCenter)

        root.addStretch(1)

        # --- buttons ------------------------------------------------------
        row = QHBoxLayout()
        row.addStretch(1)

        choose = QPushButton("Choose Folder…")
        choose.setDefault(True)
        choose.setStyleSheet(
            "QPushButton { background: #2b5fa1; color: white; "
            "              font-weight: bold; padding: 9px 20px; "
            "              border: none; border-radius: 4px; }"
            "QPushButton:hover  { background: #3b7ec9; }"
            "QPushButton:pressed{ background: #24528b; }")
        choose.clicked.connect(self._choose_folder)
        row.addWidget(choose)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            "QPushButton { background: #333333; color: white; "
            "              padding: 9px 20px; border: none; "
            "              border-radius: 4px; }"
            "QPushButton:hover { background: #444444; }")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        row.addStretch(1)
        root.addLayout(row)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select a folder of videos", os.path.expanduser("~"))
        if folder:
            self.chosen_folder = folder
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

        # VLC
        self.vlc_instance = vlc.Instance(["--no-video-title-show"])
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
        self.current_video_path: str | None = None
        self.current_video_idx: int | None = None

        # Central pages (grid / video) in a stack
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_menu()
        self._build_grid_page()
        self._build_video_page()
        self._build_close_overlay()
        self._build_set_thumb_overlay()
        self._build_jog_overlay()
        self._build_overlay_toggle()
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

        file_menu = menu.addMenu("&File")
        open_act = QAction("Open Folder…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._show_open_dialog)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.setShortcut(QKeySequence.StandardKey.Quit)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        help_menu = menu.addMenu("&Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

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

    def _build_close_overlay(self) -> None:
        """Floating X button shown over the video while playing.

        Parented to the main window (not the stack page) and given its
        own native surface via WA_NativeWindow so it composites cleanly
        on top of VLC's video output on every platform.
        """
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("closeOverlay")
        self.close_button.setFixedSize(48, 48)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip("Close video and return to grid (Esc)")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setAttribute(
            Qt.WidgetAttribute.WA_NativeWindow, True)
        # Make the native surface translucent so only the rounded button
        # shape is painted — otherwise the native window is opaque black
        # and you see a rectangle around the circular button.
        self.close_button.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.close_button.setAutoFillBackground(False)
        self.close_button.setStyleSheet(
            "#closeOverlay {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  color: white;"
            "  border: 2px solid rgba(255, 255, 255, 90);"
            "  border-radius: 24px;"
            "  font-size: 22px;"
            "  font-weight: bold;"
            "}"
            "#closeOverlay:hover {"
            "  background-color: rgba(210, 50, 50, 220);"
            "  border: 2px solid rgba(255, 255, 255, 180);"
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
        self.close_button.move(max(0, x), max(0, y))
        self.close_button.raise_()

    # ---------------------------------------------- "Set Thumbnail" overlay --
    def _build_set_thumb_overlay(self) -> None:
        """A pill-shaped button overlaid on the top-right of the video that
        captures the current frame and uses it as the grid thumbnail for
        the video being played. It sits just to the left of the ✕ button.
        """
        self.set_thumb_button = QPushButton("\u25A3  Set Thumbnail", self)
        self.set_thumb_button.setObjectName("setThumbOverlay")
        self.set_thumb_button.setFixedHeight(40)
        self.set_thumb_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_thumb_button.setToolTip(
            "Use the current frame as this video's grid thumbnail")
        self.set_thumb_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_thumb_button.setAttribute(
            Qt.WidgetAttribute.WA_NativeWindow, True)
        # See the close button for why this is needed — keeps the native
        # surface transparent so only the pill shape is painted, not the
        # surrounding rectangle.
        self.set_thumb_button.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.set_thumb_button.setAutoFillBackground(False)
        self.set_thumb_button.setStyleSheet(
            "#setThumbOverlay {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  color: white;"
            "  border: 2px solid rgba(255, 255, 255, 90);"
            "  border-radius: 20px;"
            "  font-size: 13px;"
            "  font-weight: bold;"
            "  padding: 0 18px;"
            "}"
            "#setThumbOverlay:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "  border: 2px solid rgba(255, 255, 255, 180);"
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
        self.set_thumb_button.adjustSize()
        # adjustSize() respects text width but we forced a fixed height earlier.
        self.set_thumb_button.setFixedHeight(40)
        x = (self.close_button.x()
             - self.set_thumb_button.width() - gap)
        y = margin + (self.close_button.height() - 40) // 2
        self.set_thumb_button.move(max(0, x), max(0, y))
        # Re-apply the pill mask every time the width changes (the button
        # is resized by adjustSize() when the text changes between ▣ Set
        # Thumbnail and ✓ Thumbnail Set).
        apply_rounded_mask(self.set_thumb_button, 20)
        self.set_thumb_button.raise_()

    # ------------------------------------------------ jog / transport bar --
    def _build_jog_overlay(self) -> None:
        """Floating bottom transport bar with current time, scrubber slider,
        and total time. Composited over the VLC video output the same way
        the close button is — child of the main window with its own
        native surface so it draws cleanly on top of native video."""
        self.jog_bar = QWidget(self)
        self.jog_bar.setObjectName("jogBar")
        self.jog_bar.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.jog_bar.setAttribute(
            Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        # Translucent native surface so the rounded pill shape doesn't get
        # surrounded by an opaque black rectangle.
        self.jog_bar.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.jog_bar.setAutoFillBackground(False)
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
            "  border: 1px solid rgba(255, 255, 255, 100);"
            "  border-radius: 18px;"
            "  font-size: 15px;"
            "  padding: 0;"
            "}"
            "#pauseBtn:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "  border: 1px solid rgba(255, 255, 255, 180);"
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
        self.jog_bar.move(max(0, x), max(0, y))
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
        self.overlay_toggle.setToolTip("Hide on-screen controls")
        self.overlay_toggle.setAttribute(
            Qt.WidgetAttribute.WA_NativeWindow, True)
        self.overlay_toggle.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.overlay_toggle.setAutoFillBackground(False)
        self.overlay_toggle.setStyleSheet(
            "#overlayToggle {"
            "  background-color: rgba(0, 0, 0, 170);"
            "  color: white;"
            "  border: 1px solid rgba(255, 255, 255, 90);"
            "  border-radius: 14px;"
            "  font-size: 16px;"
            "  font-weight: bold;"
            "  padding: 0;"
            "}"
            "#overlayToggle:hover {"
            "  background-color: rgba(43, 95, 161, 220);"
            "  border: 1px solid rgba(255, 255, 255, 180);"
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
            y = self.jog_bar.y() + self.jog_bar.height() + 6
        else:
            y = self.height() - h - 14
        # Guard against falling off-screen in weird window sizes
        y = max(0, min(y, self.height() - h - 2))
        self.overlay_toggle.move(max(0, x), y)
        self.overlay_toggle.raise_()

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
        """Hide the timeline, pause, close, and Set Thumbnail buttons.
        The chevron toggle stays visible so the user can bring them back."""
        if not self.is_playing:
            return
        self._overlays_hidden = True
        self.jog_bar.hide()
        self.close_button.hide()
        self.set_thumb_button.hide()
        self.overlay_toggle.setText("\u25B4")       # ▴
        self.overlay_toggle.setToolTip("Show on-screen controls")
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
        self._position_jog_bar()
        self.jog_bar.show()
        self.jog_bar.raise_()
        self.overlay_toggle.setText("\u25BE")       # ▾
        self.overlay_toggle.setToolTip("Hide on-screen controls")
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
            self._load_folder(dlg.chosen_folder)

    def _load_folder(self, folder: str) -> None:
        try:
            entries = sorted(os.listdir(folder))
        except OSError as exc:
            QMessageBox.critical(self, "Error",
                                 f"Could not read folder:\n{exc}")
            return

        videos = [
            os.path.join(folder, n)
            for n in entries
            if n.lower().endswith(VIDEO_EXTS)
            and os.path.isfile(os.path.join(folder, n))
        ]
        if not videos:
            QMessageBox.warning(
                self, "No videos",
                "No supported video files were found in that folder.\n\n"
                "Supported extensions: " + ", ".join(VIDEO_EXTS))
            return

        self.video_files = videos[:self.grid_rows * self.grid_cols]
        self.thumbnails.clear()
        self._render_grid()

        # Swap in a new thumbnail worker (stops any previous one first)
        if self.thumb_worker is not None:
            self.thumb_worker.stop()
            self.thumb_worker.wait(2000)
        self.thumb_worker = ThumbnailWorker(
            list(self.video_files),
            use_sidecar=self.use_sidecar_thumbnails,
        )
        self.thumb_worker.thumbnail_ready.connect(self._on_thumbnail)
        self.thumb_worker.start()

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
            thumb.setMinimumSize(THUMB_W, THUMB_H)
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

        # Switch to the video page so the surface is laid out & visible,
        # then go fullscreen, then give Qt one event-loop tick so the
        # native surface is definitely realized before handing its
        # handle to VLC.
        self.stack.setCurrentWidget(self.video_page)
        self.showFullScreen()

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

        media = self.vlc_instance.media_new(path)
        self.player.set_media(media)
        self.player.play()

        # Show the floating close button and the transport bar on top
        # of the video.
        self._position_close_button()
        self.close_button.show()
        self.close_button.raise_()

        # Reset the "Set Thumbnail" button label in case it was showing
        # the "✓ Thumbnail Set" confirmation from a previous play, then
        # show it to the left of the ✕ button — but only if the user has
        # the "Show Set Thumbnail button" option enabled in the popup.
        self.set_thumb_button.setText("\u25A3  Set Thumbnail")
        if self.show_set_thumb_button:
            self._position_set_thumb_button()
            self.set_thumb_button.show()
            self.set_thumb_button.raise_()
        else:
            self.set_thumb_button.hide()

        # Reset and reveal the jog/transport bar
        self.timeline.blockSignals(True)
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        self.time_current.setText("0:00")
        self.time_total.setText("0:00")
        self._set_pause_button_state(paused=False)
        self._position_jog_bar()
        self.jog_bar.show()
        self.jog_bar.raise_()
        self.position_timer.start()

        # Controls are visible at the start of each playback; reset the
        # chevron to its "press to hide" state and show it under the bar.
        self._overlays_hidden = False
        self.overlay_toggle.setText("\u25BE")     # ▾
        self.overlay_toggle.setToolTip("Hide on-screen controls")
        self._position_overlay_toggle()
        self.overlay_toggle.show()
        self.overlay_toggle.raise_()

        # If the user asked for auto-hide, start the 5-second countdown.
        if self.auto_hide_overlays:
            self.auto_hide_timer.start()

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
        thumb_qimg = load_image_as_thumb_qimage(tmp_path)
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
        self.set_thumb_button.setText("\u2713  Thumbnail Set")
        QTimer.singleShot(
            1400,
            lambda: self.set_thumb_button.setText("\u25A3  Set Thumbnail"))

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
        QTimer.singleShot(
            0, lambda: self._set_pause_button_state(paused=False))

    def _on_vlc_end(self, _event) -> None:
        # Fires on VLC's thread — defer UI updates to the Qt main loop
        QTimer.singleShot(80, self._stop_playback)

    def _stop_playback(self) -> None:
        if not self.is_playing:
            return
        self.is_playing = False
        self.position_timer.stop()
        self.auto_hide_timer.stop()
        self.close_button.hide()
        self.set_thumb_button.hide()
        self.jog_bar.hide()
        self.overlay_toggle.hide()
        self._overlays_hidden = False
        try:
            self.player.stop()
        except Exception:
            pass
        self.current_video_path = None
        self.current_video_idx = None
        self.showNormal()
        self.stack.setCurrentWidget(self.grid_page)

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
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------------- resize --
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the floating overlays pinned to their corners on every resize
        if getattr(self, "close_button", None) is not None \
                and self.close_button.isVisible():
            self._position_close_button()
        if getattr(self, "set_thumb_button", None) is not None \
                and self.set_thumb_button.isVisible():
            self._position_set_thumb_button()
        if getattr(self, "jog_bar", None) is not None \
                and self.jog_bar.isVisible():
            self._position_jog_bar()
        if getattr(self, "overlay_toggle", None) is not None \
                and self.overlay_toggle.isVisible():
            self._position_overlay_toggle()

    # ------------------------------------------------------------------ misc --
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
        if self.thumb_worker is not None:
            self.thumb_worker.stop()
            self.thumb_worker.wait(2000)
        try:
            self.player.stop()
            self.player.release()
            self.vlc_instance.release()
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    window = VideoGridApp(initial_folder=initial)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
