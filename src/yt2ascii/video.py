"""Video metadata, duration limits, and frame decoding/sampling with OpenCV."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from .errors import DownloadError, DurationLimitError
from .youtube import RawMetadata

CaptureFactory = Callable[[str], Any]


def format_timestamp(seconds: float) -> str:
    """Format seconds as ``MM:SS`` (or ``HH:MM:SS`` past an hour)."""

    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Normalised, display-ready video metadata."""

    title: str
    duration: float
    width: int
    height: int
    fps: float

    @classmethod
    def from_raw(cls, raw: RawMetadata) -> VideoMetadata:
        return cls(
            title=raw.title,
            duration=raw.duration,
            width=raw.width,
            height=raw.height,
            fps=raw.fps,
        )

    @property
    def resolution_label(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}x{self.height}"
        return "unknown"

    @property
    def fps_label(self) -> str:
        return f"{self.fps:g}" if self.fps > 0 else "unknown"


def validate_duration(duration: float, max_duration: int) -> None:
    """Raise :class:`DurationLimitError` if ``duration`` exceeds the limit."""

    if duration > max_duration:
        raise DurationLimitError(
            f"Video duration is {format_timestamp(duration)}.\n\n"
            f"Maximum allowed duration is {format_timestamp(max_duration)}.\n\n"
            "Use --max-duration to change this limit."
        )


@dataclass(frozen=True, slots=True)
class Frame:
    """A single decoded frame ready for rendering."""

    index: int
    timestamp: float
    image: NDArray[np.uint8]  # RGB, shape (H, W, 3)


class FrameSource:
    """Decode frames from a local video file, sampled to a target FPS.

    Every source frame is *grabbed* (cheap, no decode); only the frames that
    will actually be displayed are *retrieved* and colour-converted.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        capture_factory: CaptureFactory = cv2.VideoCapture,
    ) -> None:
        self._cap = capture_factory(str(path))
        if not self._cap.isOpened():
            raise DownloadError("Could not open the downloaded video for decoding.")

        self.source_fps: float = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.frame_count: int = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.width: int = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height: int = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()

    @property
    def duration(self) -> float:
        if self.source_fps > 0 and self.frame_count > 0:
            return self.frame_count / self.source_fps
        return 0.0

    def estimated_output_frames(self, target_fps: float) -> int:
        if self.duration > 0:
            return int(self.duration * target_fps)
        if self.frame_count > 0 and self.source_fps > 0:
            return int(self.frame_count / self.source_fps * target_fps)
        return 0

    def frames(self, target_fps: float) -> Iterator[Frame]:
        """Yield :class:`Frame` objects at approximately ``target_fps``."""

        if target_fps <= 0:
            raise ValueError("target_fps must be positive")

        src_fps = self.source_fps if self.source_fps > 0 else target_fps
        step = max(1e-6, src_fps / target_fps)  # source frames per output frame

        src_index = 0
        next_src_index = 0.0
        out_index = 0

        while self._cap.grab():
            if src_index + 1e-9 >= next_src_index:
                ok, bgr = self._cap.retrieve()
                if not ok or bgr is None:
                    break
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                yield Frame(
                    index=out_index,
                    timestamp=out_index / target_fps,
                    image=rgb,
                )
                out_index += 1
                next_src_index += step
            src_index += 1
