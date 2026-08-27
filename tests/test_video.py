"""Tests for yt2ascii.video."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from yt2ascii.errors import DownloadError, DurationLimitError
from yt2ascii.video import (
    Frame,
    FrameSource,
    VideoMetadata,
    format_timestamp,
    validate_duration,
)
from yt2ascii.youtube import RawMetadata


class FakeCapture:
    """Minimal stand-in for ``cv2.VideoCapture``."""

    def __init__(self, frames: list[np.ndarray], fps: float = 30.0, opened: bool = True) -> None:
        self._frames = frames
        self._fps = fps
        self._opened = opened
        self._pos = 0
        self._grabbed = -1
        self.released = False

    def isOpened(self) -> bool:
        return self._opened

    def get(self, prop: int) -> float:
        h, w = (self._frames[0].shape[0], self._frames[0].shape[1]) if self._frames else (0, 0)
        return {
            cv2.CAP_PROP_FPS: self._fps,
            cv2.CAP_PROP_FRAME_COUNT: float(len(self._frames)),
            cv2.CAP_PROP_FRAME_WIDTH: float(w),
            cv2.CAP_PROP_FRAME_HEIGHT: float(h),
        }.get(prop, 0.0)

    def grab(self) -> bool:
        if self._pos >= len(self._frames):
            return False
        self._grabbed = self._pos
        self._pos += 1
        return True

    def retrieve(self) -> tuple[bool, np.ndarray | None]:
        if not 0 <= self._grabbed < len(self._frames):
            return False, None
        return True, self._frames[self._grabbed]

    def set(self, prop: int, value: float) -> bool:
        if prop == cv2.CAP_PROP_POS_FRAMES:
            self._pos = int(value)
            self._grabbed = -1
            return True
        return False

    def release(self) -> None:
        self.released = True


def _solid_frames(n: int, size: tuple[int, int] = (8, 8)) -> list[np.ndarray]:
    return [np.full((*size, 3), i, dtype=np.uint8) for i in range(n)]


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0, "00:00"), (5, "00:05"), (102, "01:42"), (599, "09:59"), (3661, "01:01:01")],
    )
    def test_values(self, seconds: int, expected: str) -> None:
        assert format_timestamp(seconds) == expected

    def test_negative_clamped(self) -> None:
        assert format_timestamp(-3) == "00:00"


class TestValidateDuration:
    def test_within_limit_passes(self) -> None:
        validate_duration(120, 300)

    def test_exceeding_limit_raises_with_helpful_message(self) -> None:
        with pytest.raises(DurationLimitError) as excinfo:
            validate_duration(763, 300)
        message = str(excinfo.value)
        assert "12:43" in message
        assert "05:00" in message
        assert "--max-duration" in message


class TestVideoMetadata:
    def test_from_raw(self) -> None:
        raw = RawMetadata(
            video_id="abcdefghijk",
            title="Example",
            duration=90.0,
            width=1920,
            height=1080,
            fps=30.0,
            webpage_url="https://youtu.be/abcdefghijk",
        )
        meta = VideoMetadata.from_raw(raw)
        assert meta.title == "Example"
        assert meta.resolution_label == "1920x1080"
        assert meta.fps_label == "30"

    def test_unknown_labels(self) -> None:
        meta = VideoMetadata(title="x", duration=1.0, width=0, height=0, fps=0.0)
        assert meta.resolution_label == "unknown"
        assert meta.fps_label == "unknown"


class TestFrameSource:
    def _source(self, frames: list[np.ndarray], **kw: object) -> FrameSource:
        return FrameSource("dummy.mp4", capture_factory=lambda _p: FakeCapture(frames, **kw))  # type: ignore[arg-type]

    def test_raises_when_capture_not_open(self) -> None:
        with pytest.raises(DownloadError):
            FrameSource("x", capture_factory=lambda _p: FakeCapture([], opened=False))

    def test_reads_properties(self) -> None:
        src = self._source(_solid_frames(10), fps=25.0)
        assert src.source_fps == 25.0
        assert src.frame_count == 10
        assert (src.width, src.height) == (8, 8)
        assert src.duration == pytest.approx(10 / 25)

    def test_downsamples_to_target_fps(self) -> None:
        src = self._source(_solid_frames(30), fps=30.0)
        out = list(src.frames(target_fps=15))
        assert len(out) == 15
        assert all(isinstance(f, Frame) for f in out)
        assert out[1].timestamp == pytest.approx(1 / 15)
        # every other source frame: values 0, 2, 4, ...
        assert [int(f.image[0, 0, 0]) for f in out[:3]] == [0, 2, 4]

    def test_target_fps_above_source_yields_all_frames(self) -> None:
        src = self._source(_solid_frames(10), fps=10.0)
        assert len(list(src.frames(target_fps=30))) == 10

    def test_converts_bgr_to_rgb(self) -> None:
        bgr = np.zeros((4, 4, 3), dtype=np.uint8)
        bgr[..., 0] = 255  # blue channel in BGR
        src = self._source([bgr], fps=1.0)
        frame = next(iter(src.frames(target_fps=1)))
        assert tuple(frame.image[0, 0]) == (0, 0, 255)  # red channel in RGB

    def test_context_manager_releases(self) -> None:
        cap = FakeCapture(_solid_frames(3))
        with FrameSource("x", capture_factory=lambda _p: cap):
            pass
        assert cap.released is True

    def test_frames_rejects_bad_fps(self) -> None:
        src = self._source(_solid_frames(3))
        with pytest.raises(ValueError):
            list(src.frames(target_fps=0))

    def test_reset_allows_replay(self) -> None:
        src = self._source(_solid_frames(6), fps=6.0)
        first = list(src.frames(target_fps=6))
        assert len(first) == 6
        src.reset()
        assert len(list(src.frames(target_fps=6))) == 6
