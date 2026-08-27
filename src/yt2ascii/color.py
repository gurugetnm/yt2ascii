"""Colour maths: luminance and RGB -> ANSI escape sequences.

Array helpers accept NumPy arrays with a trailing RGB axis of size 3 and
``uint8`` or float values in ``0..255``. Scalar helpers are provided for tests
and one-off conversions.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

#: ANSI "reset all attributes" sequence.
RESET: str = "\033[0m"

# ITU-R BT.709 luminance coefficients (Y = 0.2126R + 0.7152G + 0.0722B).
_LUMA_WEIGHTS: NDArray[np.float32] = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def luminance(rgb: NDArray[np.generic]) -> NDArray[np.float32]:
    """Return per-pixel luminance in ``0..255`` for an ``(..., 3)`` RGB array."""

    arr = np.asarray(rgb, dtype=np.float32)
    if arr.shape[-1] != 3:
        raise ValueError("luminance() expects a trailing RGB axis of size 3")
    return arr @ _LUMA_WEIGHTS


def _clamp_channel(value: int) -> int:
    return 0 if value < 0 else 255 if value > 255 else value


def truecolor_fg(r: int, g: int, b: int) -> str:
    """24-bit foreground colour escape: ``ESC[38;2;R;G;Bm``."""

    return (
        f"\033[38;2;{_clamp_channel(int(r))};"
        f"{_clamp_channel(int(g))};{_clamp_channel(int(b))}m"
    )


def rgb_to_ansi256(r: int, g: int, b: int) -> int:
    """Map an RGB triple to the closest xterm-256 palette index (16-255).

    Uses the widely-adopted approximation: near-grey colours snap to the 24-step
    grey ramp (232-255); everything else snaps to the 6x6x6 colour cube.
    """

    r, g, b = _clamp_channel(int(r)), _clamp_channel(int(g)), _clamp_channel(int(b))

    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 23)

    return (
        16
        + 36 * round(r / 255 * 5)
        + 6 * round(g / 255 * 5)
        + round(b / 255 * 5)
    )


def ansi256_fg(index: int) -> str:
    """256-colour foreground escape: ``ESC[38;5;Nm``."""

    idx = int(index)
    if not 0 <= idx <= 255:
        raise ValueError("ANSI-256 colour index must be in 0..255")
    return f"\033[38;5;{idx}m"


def rgb_to_ansi256_array(rgb: NDArray[np.generic]) -> NDArray[np.int16]:
    """Vectorised :func:`rgb_to_ansi256` for an ``(..., 3)`` array."""

    arr = np.asarray(rgb).astype(np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    cube = 16 + (
        36 * np.round(r / 255 * 5)
        + 6 * np.round(g / 255 * 5)
        + np.round(b / 255 * 5)
    )

    grey = 232 + np.round((r - 8) / 247 * 23)
    grey = np.clip(grey, 232, 255)
    grey = np.where(r < 8, 16, grey)
    grey = np.where(r > 248, 231, grey)

    is_grey = (r == g) & (g == b)
    return np.where(is_grey, grey, cube).astype(np.int16)
