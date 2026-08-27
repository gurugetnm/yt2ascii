"""Tests for yt2ascii.ascii_renderer."""

from __future__ import annotations

import numpy as np
import pytest

from yt2ascii.ascii_renderer import AsciiRenderer, Dimensions, compute_dimensions
from yt2ascii.color import RESET
from yt2ascii.config import ColorMode, Config


def _strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


class TestComputeDimensions:
    def test_square_frame_halves_rows_for_cell_ratio(self) -> None:
        dims = compute_dimensions(100, 100, 80, cell_aspect_ratio=2.0)
        assert dims.cols == 80
        assert dims.rows == 40

    def test_widescreen_frame(self) -> None:
        dims = compute_dimensions(1920, 1080, 120, cell_aspect_ratio=2.0)
        assert dims.cols == 120
        assert dims.rows == round(120 * (1080 / 1920) / 2.0)

    def test_max_height_clamp(self) -> None:
        dims = compute_dimensions(100, 400, 80, cell_aspect_ratio=2.0, max_height=30)
        assert dims.rows == 30

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError):
            compute_dimensions(0, 100, 80, cell_aspect_ratio=2.0)
        with pytest.raises(ValueError):
            compute_dimensions(100, 100, 0, cell_aspect_ratio=2.0)


def _renderer(**kwargs: object) -> AsciiRenderer:
    return AsciiRenderer(Config(**kwargs))  # type: ignore[arg-type]


class TestRender:
    dims = Dimensions(cols=10, rows=4)

    def test_black_image_is_darkest_char(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE)
        frame = np.zeros((40, 100, 3), dtype=np.uint8)
        out = r.render(frame, self.dims)
        assert set(out) <= {" ", "\n"}
        assert out.split("\n")[0] == " " * 10

    def test_white_image_is_brightest_char(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE)
        frame = np.full((40, 100, 3), 255, dtype=np.uint8)
        out = r.render(frame, self.dims)
        assert out.split("\n")[0] == "@" * 10

    def test_output_grid_shape(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE)
        frame = np.full((40, 100, 3), 128, dtype=np.uint8)
        lines = r.render(frame, self.dims).split("\n")
        assert len(lines) == self.dims.rows
        assert all(len(line) == self.dims.cols for line in lines)

    def test_horizontal_gradient_is_monotonic(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE, chars=" .:-=+*#%@")
        gradient = np.linspace(0, 255, 200, dtype=np.uint8)
        frame = np.repeat(gradient[None, :, None], 40, axis=0)
        frame = np.repeat(frame, 3, axis=2)
        row = r.render(frame, Dimensions(cols=20, rows=4)).split("\n")[0]
        ramp = " .:-=+*#%@"
        positions = [ramp.index(c) for c in row]
        assert positions == sorted(positions)
        assert positions[0] == 0
        assert positions[-1] == len(ramp) - 1

    def test_custom_char_set(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE, chars="AB")
        frame = np.full((10, 10, 3), 255, dtype=np.uint8)
        assert set(r.render(frame, Dimensions(4, 2)).replace("\n", "")) == {"B"}

    @pytest.mark.parametrize("width", [20, 60, 120, 200])
    def test_various_widths(self, width: int) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE)
        frame = np.full((100, 100, 3), 200, dtype=np.uint8)
        dims = compute_dimensions(100, 100, width, cell_aspect_ratio=2.0)
        lines = r.render(frame, dims).split("\n")
        assert len(lines[0]) == width

    def test_truecolor_output_has_escapes_and_reset(self) -> None:
        r = _renderer(mode=ColorMode.TRUECOLOR)
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        frame[:, :5] = (255, 0, 0)
        frame[:, 5:] = (0, 0, 255)
        out = r.render(frame, Dimensions(10, 3))
        assert "\033[38;2;255;0;0m" in out
        assert "\033[38;2;0;0;255m" in out
        assert out.endswith(RESET)
        assert len(_strip_ansi(out).split("\n")) == 3
        assert all(len(line) == 10 for line in _strip_ansi(out).split("\n"))

    def test_truecolor_uses_run_length_encoding(self) -> None:
        r = _renderer(mode=ColorMode.TRUECOLOR)
        frame = np.full((10, 40, 3), (10, 20, 30), dtype=np.uint8)
        out = r.render(frame, Dimensions(20, 3))
        # One solid colour -> exactly one colour escape for the whole frame.
        assert out.count("\033[38;2;") == 1

    def test_grayscale_has_no_escapes(self) -> None:
        r = _renderer(mode=ColorMode.GRAYSCALE)
        frame = np.random.default_rng(1).integers(0, 256, (30, 30, 3), dtype=np.uint8)
        out = r.render(frame, Dimensions(12, 6))
        assert "\033[" not in out

    def test_ansi256_output(self) -> None:
        r = _renderer(mode=ColorMode.ANSI256)
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        frame[:, :5] = (255, 255, 255)
        out = r.render(frame, Dimensions(10, 3))
        assert "\033[38;5;" in out
        assert out.endswith(RESET)

    def test_rejects_non_rgb_frame(self) -> None:
        r = _renderer()
        with pytest.raises(ValueError):
            r.render(np.zeros((10, 10), dtype=np.uint8), self.dims)
