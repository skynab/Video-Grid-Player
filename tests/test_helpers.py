"""Unit tests for the pure helpers in ``video_grid``.

The GUI surface (QMainWindow, VLC playback, OpenCV decoding) is out of
scope for CI — instead we focus on small, deterministic functions
where regressions cost actual user-visible bugs:

* Thumbnail resolution lookup
* Time formatting in the playback overlay
* QSettings type coercion (the source of past bugs where stored values
  came back as strings on Linux but as Python types on macOS)
* Cached-thumbnail path derivation (must be deterministic & unique)
* Sidecar image discovery
* The non-Windows branch of the path-mangling helper
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import video_grid as vg


# ---------------------------------------------------------------------------
# thumbnail resolution lookup
# ---------------------------------------------------------------------------
def test_thumb_size_for_each_known_key():
    assert vg.thumb_size_for(vg.THUMB_RES_STANDARD) == (640, 360)
    assert vg.thumb_size_for(vg.THUMB_RES_HIGH) == (1280, 720)
    assert vg.thumb_size_for(vg.THUMB_RES_ULTRA) == (1920, 1080)


def test_thumb_size_for_unknown_key_falls_back_to_default():
    fallback = vg.THUMB_RESOLUTIONS[vg.DEFAULT_THUMB_RES]
    assert vg.thumb_size_for("not-a-real-resolution") == fallback
    assert vg.thumb_size_for("") == fallback


def test_default_thumb_res_is_a_known_key():
    # Guards against accidentally setting DEFAULT_THUMB_RES to a value
    # that isn't in THUMB_RESOLUTIONS — that would silently fall through
    # to a different default for every caller.
    assert vg.DEFAULT_THUMB_RES in vg.THUMB_RESOLUTIONS


# ---------------------------------------------------------------------------
# _format_time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ms, expected",
    [
        (0, "0:00"),
        (1_000, "0:01"),
        (45_000, "0:45"),
        (60_000, "1:00"),
        (125_000, "2:05"),
        (3_599_000, "59:59"),
        (3_600_000, "1:00:00"),
        (3_605_000, "1:00:05"),
        (10_805_000, "3:00:05"),
    ],
)
def test_format_time_shapes(ms, expected):
    assert vg.VideoGridApp._format_time(ms) == expected


@pytest.mark.parametrize("bad", [-1, -10_000, None])
def test_format_time_handles_unknown_or_negative(bad):
    assert vg.VideoGridApp._format_time(bad) == "0:00"


# ---------------------------------------------------------------------------
# _coerce — QSettings round-trips
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("true", True), ("True", True), ("1", True),
        ("yes", True), ("on", True),
        ("false", False), ("False", False), ("0", False),
        ("no", False), ("off", False),
    ],
)
def test_coerce_bool_from_string(raw, expected):
    assert vg.VideoGridApp._coerce(raw, bool, not expected) is expected


def test_coerce_bool_passthrough():
    assert vg.VideoGridApp._coerce(True, bool, False) is True
    assert vg.VideoGridApp._coerce(False, bool, True) is False


def test_coerce_bool_unrecognized_string_is_falsy():
    # The implementation treats anything outside the truthy whitelist as
    # False rather than falling back — pin that contract so a future
    # refactor doesn't quietly change it.
    assert vg.VideoGridApp._coerce("maybe", bool, True) is False
    assert vg.VideoGridApp._coerce("", bool, True) is False


def test_coerce_bool_none_uses_fallback():
    assert vg.VideoGridApp._coerce(None, bool, True) is True
    assert vg.VideoGridApp._coerce(None, bool, False) is False


def test_coerce_int_from_string():
    assert vg.VideoGridApp._coerce("42", int, 0) == 42
    assert vg.VideoGridApp._coerce("-3", int, 0) == -3


def test_coerce_int_invalid_falls_back():
    assert vg.VideoGridApp._coerce("not-a-number", int, 7) == 7
    assert vg.VideoGridApp._coerce(None, int, 99) == 99


def test_coerce_str():
    assert vg.VideoGridApp._coerce("hello", str, "x") == "hello"
    assert vg.VideoGridApp._coerce(None, str, "fallback") == "fallback"


# ---------------------------------------------------------------------------
# _cached_thumb_path — must be deterministic and per-video unique
# ---------------------------------------------------------------------------
def test_cached_thumb_path_is_deterministic():
    a = vg._cached_thumb_path("/movies/holiday.mp4")
    b = vg._cached_thumb_path("/movies/holiday.mp4")
    assert a == b
    assert a.suffix == ".png"


def test_cached_thumb_path_unique_per_video():
    a = vg._cached_thumb_path("/movies/holiday.mp4")
    b = vg._cached_thumb_path("/movies/birthday.mp4")
    assert a != b


def test_cached_thumb_path_lives_in_cache_dir():
    p = vg._cached_thumb_path("/movies/holiday.mp4")
    assert vg._cache_dir() in p.parents


# ---------------------------------------------------------------------------
# _cv_safe_path — pure on non-Windows; ASCII passthrough on Windows
# ---------------------------------------------------------------------------
def test_cv_safe_path_returns_input_on_non_windows(monkeypatch):
    monkeypatch.setattr(vg.sys, "platform", "linux")
    assert vg._cv_safe_path("/tmp/holiday.mp4") == "/tmp/holiday.mp4"


def test_cv_safe_path_passthrough_for_ascii_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(vg.sys, "platform", "win32")
    target = tmp_path / "ascii_only.mp4"
    target.write_bytes(b"x")
    # Pure ASCII paths should return unchanged (abspath, but no short-name
    # translation needed). We compare on the resolved absolute path so
    # the test works regardless of how tmp_path is reported.
    got = vg._cv_safe_path(str(target))
    assert os.path.abspath(got) == os.path.abspath(str(target))


# ---------------------------------------------------------------------------
# _find_sidecar_image — match base name across supported extensions
# ---------------------------------------------------------------------------
def test_find_sidecar_image_matches_jpg(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    sidecar = tmp_path / "clip.jpg"
    sidecar.write_bytes(b"")
    found = vg._find_sidecar_image(str(video))
    assert found is not None
    assert Path(found).name == "clip.jpg"


def test_find_sidecar_image_returns_none_when_absent(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    assert vg._find_sidecar_image(str(video)) is None


def test_find_sidecar_image_ignores_unsupported_extensions(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    # .tiff is not in the supported sidecar list, so this shouldn't match.
    (tmp_path / "clip.tiff").write_bytes(b"")
    assert vg._find_sidecar_image(str(video)) is None
