"""Convert a single decoded video frame into a coloured ANSI ASCII string.

The renderer is stateless between frames and never touches the terminal; it
returns a plain multi-line string. Cursor positioning and writing are the
terminal/player's job.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from .color import RESET, luminance, rgb_to_ansi256_array
from .config import ColorMode, Config


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Target ASCII grid size, in character cells."""

    cols: int
    rows: int


def compute_dimensions(
    frame_width: int,
    frame_height: int,
    target_width: int,
    *,
    cell_aspect_ratio: float,
    max_height: int | None = None,
    fill_height: int | None = None,
) -> Dimensions:
    """Derive the ASCII grid size for a frame.

    ``rows`` normally accounts for the video aspect ratio and the fact that a
    terminal cell is roughly ``cell_aspect_ratio`` times taller than it is
    wide, so the image is not vertically stretched. Pass ``fill_height`` to
    force an exact row count instead (stretch-to-fill, ignoring aspect ratio).
    """

    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")
    if target_width <= 0:
        raise ValueError("target_width must be positive")

    cols = int(target_width)

    if fill_height is not None:
        return Dimensions(cols=cols, rows=max(1, int(fill_height)))

    frame_aspect = frame_height / frame_width
    rows = max(1, round(cols * frame_aspect / cell_aspect_ratio))

    if max_height is not None and rows > max_height:
        rows = max(1, int(max_height))

    return Dimensions(cols=cols, rows=rows)


class AsciiRenderer:
    """Turn RGB frames into coloured ASCII according to a :class:`Config`."""

    def __init__(self, config: Config) -> None:
        self._chars: NDArray[np.str_] = np.array(list(config.chars), dtype="<U1")
        self._ramp_max = len(config.chars) - 1
        self._mode = config.effective_mode

    @property
    def mode(self) -> ColorMode:
        return self._mode

    def render(self, frame_rgb: NDArray[np.generic], dims: Dimensions) -> str:
        """Render ``frame_rgb`` (an ``(H, W, 3)`` RGB array) to an ANSI string."""

        if frame_rgb.ndim != 3 or frame_rgb.shape[2] != 3:
            raise ValueError("frame_rgb must have shape (H, W, 3)")

        resized = cv2.resize(
            np.ascontiguousarray(frame_rgb),
            (dims.cols, dims.rows),
            interpolation=cv2.INTER_AREA,
        ).astype(np.uint8)

        lum = luminance(resized)  # (rows, cols), 0..255
        idx = np.clip(
            np.rint(lum / 255.0 * self._ramp_max), 0, self._ramp_max
        ).astype(np.intp)
        chars = self._chars[idx]  # (rows, cols) of single characters

        if self._mode is ColorMode.GRAYSCALE:
            return "\n".join("".join(row) for row in chars)
        if self._mode is ColorMode.ANSI256:
            return self._colorize(chars, self._ansi256_codes(resized))
        return self._colorize(chars, self._truecolor_codes(resized))

    @staticmethod
    def _run_starts(flat_changed: NDArray[np.bool_]) -> NDArray[np.bool_]:
        """Length ``N`` mask (``N = flat_changed.size + 1``): ``True`` where a
        new colour run starts (row-major). The first cell always starts a run."""

        starts = np.empty(flat_changed.shape[0] + 1, dtype=bool)
        starts[0] = True
        starts[1:] = flat_changed
        return starts

    def _truecolor_codes(self, rgb: NDArray[np.uint8]) -> NDArray[np.object_]:
        flat = rgb.reshape(-1, 3).astype(int)
        changed = np.any(flat[1:] != flat[:-1], axis=1)
        starts = self._run_starts(changed)

        codes = np.full(flat.shape[0], "", dtype=object)
        for i in np.nonzero(starts)[0]:
            r, g, b = flat[i]
            codes[i] = f"\033[38;2;{r};{g};{b}m"
        return codes.reshape(rgb.shape[:2])

    def _ansi256_codes(self, rgb: NDArray[np.uint8]) -> NDArray[np.object_]:
        indices = rgb_to_ansi256_array(rgb).reshape(-1)
        changed = indices[1:] != indices[:-1]
        starts = self._run_starts(changed)

        codes = np.full(indices.shape[0], "", dtype=object)
        for i in np.nonzero(starts)[0]:
            codes[i] = f"\033[38;5;{int(indices[i])}m"
        return codes.reshape(rgb.shape[:2])

    @staticmethod
    def _colorize(
        chars: NDArray[np.str_], codes: NDArray[np.object_]
    ) -> str:
        combined = codes + chars.astype(object)  # elementwise string concat
        lines = ["".join(row) for row in combined]
        return "\n".join(lines) + RESET
