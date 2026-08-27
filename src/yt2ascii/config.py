"""Runtime configuration for a single yt2ascii playback session."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .errors import ConfigError

#: Default luminance -> character ramp, dark to light.
DEFAULT_CHARS: str = " .:-=+*#%@"

#: Hard cap on the ASCII width regardless of terminal size or ``--width``.
MAX_WIDTH: int = 200

#: Smallest width that still produces a recognisable image.
MIN_WIDTH: int = 20

#: Safety margin (columns) subtracted from the detected terminal width.
WIDTH_SAFETY_MARGIN: int = 2

DEFAULT_FPS: int = 15
MIN_FPS: int = 1
MAX_FPS: int = 60

DEFAULT_MAX_DURATION: int = 300

#: Height / width ratio of a single terminal character cell. Terminal cells are
#: roughly twice as tall as they are wide, so vertical resolution is halved.
DEFAULT_CELL_ASPECT_RATIO: float = 2.0


class ColorMode(StrEnum):
    """Supported colour rendering strategies."""

    TRUECOLOR = "truecolor"
    ANSI256 = "ansi256"
    GRAYSCALE = "grayscale"


@dataclass(frozen=True, slots=True)
class Config:
    """Validated configuration derived from CLI options.

    ``width`` is ``None`` when it should be derived from the live terminal size
    at playback time.
    """

    width: int | None = None
    fps: int = DEFAULT_FPS
    mode: ColorMode = ColorMode.TRUECOLOR
    chars: str = DEFAULT_CHARS
    grayscale: bool = False
    max_duration: int = DEFAULT_MAX_DURATION
    cell_aspect_ratio: float = DEFAULT_CELL_ASPECT_RATIO

    def __post_init__(self) -> None:
        if self.width is not None:
            if self.width < MIN_WIDTH:
                raise ConfigError(
                    f"--width must be at least {MIN_WIDTH} columns (got {self.width})."
                )
            if self.width > MAX_WIDTH:
                raise ConfigError(
                    f"--width must be at most {MAX_WIDTH} columns (got {self.width})."
                )
        if not (MIN_FPS <= self.fps <= MAX_FPS):
            raise ConfigError(
                f"--fps must be between {MIN_FPS} and {MAX_FPS} (got {self.fps})."
            )
        if len(self.chars) < 2:
            raise ConfigError("--chars must contain at least two characters (dark to light).")
        if self.max_duration <= 0:
            raise ConfigError("--max-duration must be a positive number of seconds.")
        if self.cell_aspect_ratio <= 0:
            raise ConfigError("cell_aspect_ratio must be positive.")

    @property
    def effective_mode(self) -> ColorMode:
        """Colour mode after applying the ``--grayscale`` shortcut."""

        return ColorMode.GRAYSCALE if self.grayscale else self.mode

    def with_width(self, width: int) -> Config:
        """Return a copy with ``width`` resolved to a concrete value."""

        return replace(self, width=width)
