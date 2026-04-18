Video Grid Player
=================

A cross-platform desktop app (Windows / macOS / Linux) that shows your
videos in a configurable grid (up to 6 rows x 6 columns, default 3x4)
with real thumbnail previews extracted from each video. Each cell can
show the file name (extension hidden) as a title. Clicking a cell plays
the video FULLSCREEN INSIDE THE SAME APPLICATION (no external player is
launched). A floating circular X button and a bottom scrubber/timeline
are overlaid on the video while playing. When playback finishes (or
Escape is pressed, or the X is clicked) the app returns to the grid
view.

The folder-picker opens in a clean modal popup — either automatically on
startup, or from File -> Open Folder... — so the main window stays
uncluttered. The popup also lets you:

  * Pick the number of rows and columns (1-6 each)
  * Show or hide the video titles in the grid
  * Choose between a spaced grid layout or a full-width layout with
    no gaps or padding between videos


ARCHITECTURE
------------
GUI is PyQt6 (so native window handles are available on every OS —
Tkinter on macOS cannot provide a usable NSView, which is why the
earlier Tk version could not embed on Mac). Playback uses libvlc via
python-vlc rendered directly into a QWidget. Thumbnails are extracted
with OpenCV on a background QThread.


REQUIREMENTS
------------
1. Python 3.8 or newer
2. VLC media player installed on your system
     - Windows : https://www.videolan.org/   (use the 64-bit build that
                 matches your Python architecture)
     - macOS   : `brew install --cask vlc`   or download from videolan.org
     - Linux   : `sudo apt install vlc`      (or your distro's equivalent)
3. Python packages:
       pip install PyQt6 python-vlc opencv-python


RUNNING
-------
    python video_grid.py                      # launches with the popup picker
    python video_grid.py "/path/to/videos"    # preload a folder, skip popup

Or use File -> Open Folder... from inside the app at any time.

The app scans the chosen folder for the following extensions and loads
the first N files (alphabetical), where N is rows x columns:

    .mp4 .mkv .avi .mov .webm .wmv .flv .m4v .mpg .mpeg .ts


CONTROLS
--------
  Click a cell      Play that video fullscreen, inside the app
  Click the ✕       Stop playback and return to the grid
  Drag timeline     Scrub to any position in the video
  Esc               Stop playback and return to the grid
  Space             Pause / resume the current video
  Left / Right      Seek 5 seconds back / forward
  Ctrl+O / Cmd+O    Open folder
  Ctrl+Q / Cmd+Q    Quit


NOTES
-----
* Thumbnails are decoded on a background thread, so the grid appears
  immediately and each cell's preview fills in asynchronously. A
  "Loading thumbnail…" placeholder is shown in the meantime.
* Each thumbnail is taken from roughly 10% into the video to avoid
  black intros and studio logos.
* On macOS, if python-vlc imports but video fails to start, your Python
  architecture (arm64 vs x86_64) likely doesn't match the installed
  VLC. Install the matching VLC build.
