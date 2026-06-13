# VideoGridPlayer.spec
# ---------------------------------------------------------------------------
# PyInstaller spec file for Video Grid Player.
#
# Build locally (from the project root):
#   pip install pyinstaller
#   pyinstaller VideoGridPlayer.spec
#
# Output lands in dist/VideoGridPlayer/ (one-folder mode for fast startup).
#
# VLC libraries
# -------------
# python-vlc is a thin Python binding that calls into libvlc at runtime.
# The native VLC libraries are NOT bundled automatically by PyInstaller, so
# we locate and copy them here.  If VLC is not installed on the build machine
# the build will succeed but the app will crash on launch for the end-user
# unless they install VLC themselves.  The CI workflow installs VLC before
# running this spec so the libraries are always present on the build runner.
# ---------------------------------------------------------------------------

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# ---------------------------------------------------------------------------
# Locate VLC's native library directory
# ---------------------------------------------------------------------------
def find_vlc_lib_dir() -> Path | None:
    """Return the directory that contains libvlc + the plugins/ subdirectory,
    or None if VLC is not found.  Checked in order of likelihood per platform."""
    candidates: list[Path] = []

    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/VLC.app/Contents/MacOS/lib"),
            Path("/opt/homebrew/lib"),
            Path("/usr/local/lib"),
        ]
    elif sys.platform == "win32":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "VideoLAN" / "VLC",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "VideoLAN" / "VLC",
        ]
    else:  # Linux
        candidates = [
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/usr/lib/aarch64-linux-gnu"),
            Path("/usr/lib"),
            Path("/usr/local/lib"),
        ]

    for path in candidates:
        if path.exists():
            # Confirm libvlc is actually here
            lib_name = "libvlc.dylib" if sys.platform == "darwin" else \
                       "libvlc.dll"   if sys.platform == "win32"  else \
                       "libvlc.so.5"
            if (path / lib_name).exists():
                return path
            # Fallback: any libvlc file
            if any(path.glob("libvlc*")):
                return path

    return None


def collect_vlc_binaries() -> list[tuple[str, str]]:
    """Return a list of (src, dest_dir) tuples for all VLC native libraries."""
    binaries = []
    vlc_dir = find_vlc_lib_dir()

    if vlc_dir is None:
        print("WARNING: VLC libraries not found — the app will require VLC "
              "to be installed on the end-user's machine.")
        return binaries

    print(f"Bundling VLC libraries from: {vlc_dir}")

    if sys.platform == "win32":
        # On Windows, libvlc.dll and libvlccore.dll live directly in the VLC
        # install folder alongside a plugins/ subdirectory.
        for f in vlc_dir.glob("libvlc*.dll"):
            binaries.append((str(f), "."))
        plugins_dir = vlc_dir / "plugins"
        if plugins_dir.exists():
            for f in plugins_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(vlc_dir)
                    binaries.append((str(f), str(rel.parent)))

    elif sys.platform == "darwin":
        # On macOS the dylibs and plugins/ are in .../VLC.app/Contents/MacOS/lib
        for f in vlc_dir.glob("libvlc*.dylib"):
            binaries.append((str(f), "lib"))
        plugins_dir = vlc_dir / "plugins"
        if not plugins_dir.exists():
            # Homebrew layout: plugins live one level up from lib/
            plugins_dir = vlc_dir.parent / "plugins"
        if plugins_dir.exists():
            for f in plugins_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(plugins_dir.parent)
                    binaries.append((str(f), str(Path("lib") / rel.parent)))

    else:  # Linux
        for f in vlc_dir.glob("libvlc*.so*"):
            binaries.append((str(f), "."))
        # Look for plugins in standard locations
        for plugin_root in [
            vlc_dir / "vlc" / "plugins",
            Path("/usr/lib/vlc/plugins"),
            Path("/usr/lib/x86_64-linux-gnu/vlc/plugins"),
        ]:
            if plugin_root.exists():
                for f in plugin_root.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(plugin_root.parent.parent)
                        binaries.append((str(f), str(rel.parent)))
                break

    return binaries


# ---------------------------------------------------------------------------
# Data files — non-Python assets that must be shipped alongside the app
# ---------------------------------------------------------------------------
added_datas = [
    # translations.py must travel with the app
    ("translations.py", "."),
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ["video_grid.py"],
    pathex=[],
    binaries=collect_vlc_binaries(),
    datas=added_datas,
    hiddenimports=[
        # python-vlc uses ctypes; PyInstaller may miss these
        "ctypes",
        "ctypes.util",
        # PyQt6 plugins used at runtime
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtNetwork",
        # OpenCV
        "cv2",
        # Standard library modules imported inside functions
        "json",
        "ssl",
        "urllib.parse",
        "urllib.request",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle lean — these are never used
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "notebook",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # one-folder mode: binaries go in the collect step
    name="VideoGridPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                # compress if UPX is available (reduces size)
    console=False,           # no terminal window — GUI-only app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",   # uncomment and point at an .ico / .icns file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoGridPlayer",
)

# macOS: wrap everything into a proper .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="VideoGridPlayer.app",
        # icon="assets/icon.icns",   # uncomment and point at an .icns file
        bundle_identifier="com.videogridplayer.app",
        info_plist={
            "CFBundleShortVersionString": "1.2.0",
            "CFBundleVersion":            "1.2.0",
            "NSHighResolutionCapable":    True,
            "NSHumanReadableCopyright":   "Video Grid Player",
        },
    )
