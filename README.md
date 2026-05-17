# Video Grid Player

A cross-platform desktop app (Windows / macOS / Linux?) that shows your videos in a configurable grid (up to 6 rows × 6 columns, default 3×4) with real thumbnail previews extracted from each video. Each cell can show the file name (extension hidden) as a title. Clicking a cell plays the video **fullscreen inside the same application** — no external player is launched. A floating circular ✕ button and a bottom scrubber/timeline are overlaid on the video while playing. When playback finishes, or `Esc` is pressed, or the ✕ is clicked, the app returns to the grid view.

The folder picker opens in a clean modal popup — either automatically on startup, or from **File → Open Folder…** — so the main window stays uncluttered. The popup also lets you:

- Pick the number of rows and columns (1–6 each)
- Show or hide the video titles in the grid
- Choose between a spaced grid layout or a full-width layout with no gaps or padding between videos
- Optionally use a matching image file next to each video (e.g. `clip.jpg` next to `clip.mp4`) as its grid thumbnail
- Pick how thumbnails fill their grid cells: either stretch to fit (distorts aspect ratio) or preserve aspect ratio and clip any overflow
- Pick the thumbnail quality / resolution:
    - **Standard** (360p, 640×360) — light and fast; best for 1080p monitors and dense grids (6×6)
    - **High** (720p, 1280×720) — crisp on 1080p, decent on 4K (default)
    - **Ultra** (1080p, 1920×1080) — best on 4K / high-DPI monitors; heaviest memory / decode cost
- Choose whether the chevron (▾) button also hides the floating close (✕) button when it collapses the on-screen controls. Turning this off keeps ✕ visible at all times so playback can always be exited with one click.

The popup also has an **"Open Last Folder"** button alongside **"Choose Folder…"**. It reuses the most recently loaded folder without going through the OS file picker, which is handy when you keep opening the same library. The button is disabled if you've never loaded a folder before, or if the previously loaded folder no longer exists on disk.

All choices in the popup (grid size, full-width layout, thumbnail resolution, sidecar images, auto-hide, shuffle, chevron behavior, last folder, etc.) are saved automatically whenever you click **Choose Folder…** or **Open Last Folder**, and restored the next time the app starts. The store lives at:

| Platform | Location |
| --- | --- |
| Windows | `HKCU\Software\VideoGridPlayer\VideoGridPlayer` (registry) |
| macOS | `~/Library/Preferences/com.VideoGridPlayer.VideoGridPlayer.plist` |
| Linux | `~/.config/VideoGridPlayer/VideoGridPlayer.conf` |

## Thumbnails

You have three ways to get thumbnails in the grid:

1. **Auto-extracted (default).** A frame from roughly 10% into each video is decoded on a background thread and shown as the thumbnail.
2. **"Set as Thumbnail" button (during playback).** While a video is playing, click the **▣ Set Thumbnail** button in the top-right corner to capture whatever frame is currently on screen and use it as the grid thumbnail for that video. The captured thumbnail is cached per-user (keyed by the video's absolute path) so it sticks around across sessions. The cache lives at:

    | Platform | Location |
    | --- | --- |
    | Windows | `%LOCALAPPDATA%\VideoGridPlayer\thumbs` |
    | macOS | `~/.cache/video_grid_player/thumbs` |
    | Linux | `~/.cache/video_grid_player/thumbs` |

3. **Sidecar image files (opt-in).** If you tick "Use matching image files as thumbnails" in the open-folder popup, the app will look for an image file sitting next to each video whose base name matches — e.g. `holiday.jpg` next to `holiday.mp4`. Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`. This option is off by default.

Priority, when deciding which thumbnail to show for a given video:

> user-set cache  >  sidecar image (if enabled)  >  auto-extracted frame

## Architecture

The GUI is PyQt6 (so native window handles are available on every OS — Tkinter on macOS cannot provide a usable `NSView`, which is why the earlier Tk version could not embed on Mac). Playback uses `libvlc` via `python-vlc` rendered directly into a `QWidget`. Thumbnails are extracted with OpenCV on a background `QThread`.

## Requirements

1. Python 3.8 or newer.
2. VLC media player installed on your system:
    - **Windows** — <https://www.videolan.org/> (use the 64-bit build that matches your Python architecture)
    - **macOS** — `brew install --cask vlc`, or download from videolan.org
    - **Linux** — `sudo apt install vlc` (or your distro's equivalent)
3. Python packages:

    ```sh
    pip install PyQt6 python-vlc opencv-python
    ```

## Running

```sh
python video_grid.py                      # launches with the popup picker
python video_grid.py "/path/to/videos"    # preload a folder, skip popup
```

## Tests

A small pytest suite under `tests/` exercises the pure helpers (thumbnail resolution lookup, time formatting, QSettings type coercion, cache path derivation, sidecar discovery). The same suite runs in CI on Ubuntu, macOS, and Windows via `.github/workflows/tests.yml` on every pull request.

To run the tests locally:

```sh
pip install PyQt6 opencv-python-headless numpy pytest
QT_QPA_PLATFORM=offscreen pytest -v tests
```

Or use **File → Open Folder…** from inside the app at any time.

The app scans the chosen folder for the following extensions and loads the first *N* files (alphabetical), where *N* is `rows × columns`:

```
.mp4  .mkv  .avi  .mov  .webm  .wmv  .flv  .m4v  .mpg  .mpeg  .ts
```

## Controls

| Action | Shortcut |
| --- | --- |
| Play a video fullscreen, inside the app | Click a cell |
| Stop playback and return to the grid | Click ✕, or `Esc` |
| Scrub to any position in the video | Drag the timeline |
| Pause / resume the current video | `Space` |
| Seek 5 seconds back / forward | `←` / `→` |
| Open folder | `Ctrl+O` / `Cmd+O` |
| Toggle application full screen (also **File → Full Screen**) | `F11` / `Ctrl+⌘+F` |
| Quit | `Ctrl+Q` / `Cmd+Q` |

## Notes

- Thumbnails are decoded on a background thread, so the grid appears immediately and each cell's preview fills in asynchronously. A "Loading thumbnail…" placeholder is shown in the meantime.
- Each thumbnail is taken from roughly 10% into the video to avoid black intros and studio logos.
- On macOS, if `python-vlc` imports but video fails to start, your Python architecture (arm64 vs x86_64) likely doesn't match the installed VLC. Install the matching VLC build.
- On Windows, if you see `[mov,mp4,m4a,3gp,3g2,mj2 @ ...] moov atom not found` in the console and thumbnails fail to load, it's usually because OpenCV's FFmpeg backend opens files through the narrow (ANSI) Windows file API, which garbles paths containing non-ASCII characters. The app already works around this by translating each path to its Windows 8.3 short form before opening and by trying multiple OpenCV backends, so the error message (if any) is cosmetic — thumbnails should still appear. If they don't, make sure short (8.3) file names aren't disabled on the drive (they are enabled by default on NTFS) and that you have a working FFmpeg build of `opencv-python` (reinstall with `pip install --upgrade --force-reinstall opencv-python` if in doubt).
