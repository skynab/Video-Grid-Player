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

import os
import sys

# ---- dependency checks ----------------------------------------------------
_missing: list[str] = []
try:
    from PyQt6.QtCore import Qt, QEvent, QTimer, QThread, pyqtSignal
    from PyQt6.QtGui import (
        QAction, QColor, QImage, QKeySequence, QPalette, QPixmap,
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

THUMB_W = 320
THUMB_H = 180

# All title boxes in the grid are pinned to this height so they line up
# visually, regardless of whether a filename happens to be long or short.
TITLE_BAR_HEIGHT = 30


# ---------------------------------------------------------------------------
# Thumbnail extraction (runs on a worker thread)
# ---------------------------------------------------------------------------
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
    h, w = rgb.shape[:2]
    scale = min(THUMB_W / w, THUMB_H / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((THUMB_H, THUMB_W, 3), dtype=np.uint8)
    y = (THUMB_H - new_h) // 2
    x = (THUMB_W - new_w) // 2
    canvas[y:y + new_h, x:x + new_w] = resized

    # .copy() detaches from the numpy buffer so the QImage survives GC
    return QImage(
        bytes(canvas.data), THUMB_W, THUMB_H, THUMB_W * 3,
        QImage.Format.Format_RGB888,
    ).copy()


class ThumbnailWorker(QThread):
    """Extract thumbnails for a list of paths off the GUI thread."""
    thumbnail_ready = pyqtSignal(int, str, QImage)

    def __init__(self, paths: list[str]):
        super().__init__()
        self._paths = paths
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        for idx, path in enumerate(self._paths):
            if self._stop:
                return
            try:
                img = extract_thumbnail(path)
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
                 full_width_default: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Open Videos")
        self.setFixedSize(540, 430)
        self.setStyleSheet("QDialog { background: #101010; }")
        self.chosen_folder: str | None = None
        self.show_titles: bool = show_titles_default
        self.grid_rows: int = rows_default
        self.grid_cols: int = cols_default
        self.full_width: bool = full_width_default

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

        # Central pages (grid / video) in a stack
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._build_menu()
        self._build_grid_page()
        self._build_video_page()
        self._build_close_overlay()
        self._build_jog_overlay()
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
        self.close_button.hide()

    def _position_close_button(self) -> None:
        """Pin the close button to the top-right corner of the window."""
        margin = 20
        x = self.width() - self.close_button.width() - margin
        y = margin
        self.close_button.move(max(0, x), max(0, y))
        self.close_button.raise_()

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
        self.jog_bar.setStyleSheet(
            "#jogBar { background-color: rgba(0, 0, 0, 180); "
            "          border-radius: 10px; }"
        )

        bar_layout = QHBoxLayout(self.jog_bar)
        bar_layout.setContentsMargins(18, 10, 18, 10)
        bar_layout.setSpacing(14)

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
        margin_y = 32
        bar_height = 56
        bar_width = max(360, self.width() - 2 * margin_x)
        self.jog_bar.setFixedHeight(bar_height)
        self.jog_bar.setFixedWidth(bar_width)
        x = (self.width() - bar_width) // 2
        y = self.height() - bar_height - margin_y
        self.jog_bar.move(max(0, x), max(0, y))
        self.jog_bar.raise_()

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
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.chosen_folder:
            self.show_titles = dlg.show_titles
            self.grid_rows = dlg.grid_rows
            self.grid_cols = dlg.grid_cols
            self.full_width = dlg.full_width
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
        self.thumb_worker = ThumbnailWorker(list(self.video_files))
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

        thumb = QLabel("Loading thumbnail…")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.full_width:
            # Let the thumbnail stretch to fill the entire cell edge-to-edge.
            thumb.setMinimumSize(1, 1)
            thumb.setScaledContents(True)
        else:
            thumb.setMinimumSize(THUMB_W, THUMB_H)
            thumb.setScaledContents(False)
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

        # Reset and reveal the jog/transport bar
        self.timeline.blockSignals(True)
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        self.time_current.setText("0:00")
        self.time_total.setText("0:00")
        self._position_jog_bar()
        self.jog_bar.show()
        self.jog_bar.raise_()
        self.position_timer.start()

    def _on_vlc_end(self, _event) -> None:
        # Fires on VLC's thread — defer UI updates to the Qt main loop
        QTimer.singleShot(80, self._stop_playback)

    def _stop_playback(self) -> None:
        if not self.is_playing:
            return
        self.is_playing = False
        self.position_timer.stop()
        self.close_button.hide()
        self.jog_bar.hide()
        try:
            self.player.stop()
        except Exception:
            pass
        self.showNormal()
        self.stack.setCurrentWidget(self.grid_page)

    # -------------------------------------------------------------- keyboard --
    def keyPressEvent(self, event):
        key = event.key()
        if self.is_playing and key == Qt.Key.Key_Escape:
            self._stop_playback()
        elif self.is_playing and key == Qt.Key.Key_Space:
            self.player.pause()
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
        if getattr(self, "jog_bar", None) is not None \
                and self.jog_bar.isVisible():
            self._position_jog_bar()

    # ------------------------------------------------------------------ misc --
    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About Video Grid Player",
            "Video Grid Player\n\n"
            "Displays up to 12 videos in a 4 × 3 grid with thumbnails. "
            "Click a cell to play the video fullscreen inside the app.\n\n"
            "Controls while playing:\n"
            "  • Esc           return to grid (or click the ✕ button)\n"
            "  • Space         pause / resume\n"
            "  • ← / →         skip 5 seconds back / forward\n"
            "  • Click / drag  on the bottom timeline to scrub\n\n"
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
