"""Tests for yt2ascii.color."""

from __future__ import annotations

import numpy as np
import pytest

from yt2ascii import color


def test_reset_sequence() -> None:
    assert color.RESET == "\033[0m"


def test_truecolor_fg_format() -> None:
    assert color.truecolor_fg(255, 100, 50) == "\033[38;2;255;100;50m"


def test_truecolor_fg_clamps_out_of_range() -> None:
    assert color.truecolor_fg(-10, 300, 128) == "\033[38;2;0;255;128m"


def test_luminance_extremes() -> None:
    black = np.zeros((2, 2, 3), dtype=np.uint8)
    white = np.full((2, 2, 3), 255, dtype=np.uint8)
    assert np.all(color.luminance(black) == 0)
    assert np.allclose(color.luminance(white), 255.0, atol=0.5)


def test_luminance_weighted_channels() -> None:
    green = np.array([[0, 255, 0]], dtype=np.uint8)
    assert color.luminance(green)[0] == pytest.approx(0.7152 * 255, abs=0.1)


def test_luminance_requires_rgb_axis() -> None:
    with pytest.raises(ValueError):
        color.luminance(np.zeros((4, 4), dtype=np.uint8))


def test_rgb_to_ansi256_greyscale_ramp() -> None:
    assert color.rgb_to_ansi256(0, 0, 0) == 16
    assert color.rgb_to_ansi256(255, 255, 255) == 231
    mid = color.rgb_to_ansi256(128, 128, 128)
    assert 232 <= mid <= 255


def test_rgb_to_ansi256_colour_cube() -> None:
    idx = color.rgb_to_ansi256(255, 0, 0)
    assert idx == 16 + 36 * 5
    assert 16 <= idx <= 231


def test_ansi256_fg_format_and_bounds() -> None:
    assert color.ansi256_fg(196) == "\033[38;5;196m"
    with pytest.raises(ValueError):
        color.ansi256_fg(256)
    with pytest.raises(ValueError):
        color.ansi256_fg(-1)


def test_rgb_to_ansi256_array_matches_scalar() -> None:
    rng = np.random.default_rng(0)
    samples = rng.integers(0, 256, size=(50, 3), dtype=np.int64)
    samples = np.vstack([samples, [[0, 0, 0], [255, 255, 255], [128, 128, 128]]])
    vector = color.rgb_to_ansi256_array(samples)
    for (r, g, b), got in zip(samples, vector, strict=True):
        assert got == color.rgb_to_ansi256(int(r), int(g), int(b))
