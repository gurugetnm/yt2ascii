"""Terminal size detection, ANSI control sequences, and safe state handling.

:class:`TerminalController` is a context manager: it hides the cursor and puts
the terminal into cbreak mode on entry, and *always* restores the cursor and
the original terminal attributes on exit -- including on ``Ctrl+C`` or an
unhandled exception.
"""

from __future__ import annotations

import os
import select
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from typing import IO

from .color import RESET
from .config import MAX_WIDTH, MIN_WIDTH, WIDTH_SAFETY_MARGIN

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_SCREEN = "\033[2J"
CLEAR_LINE = "\033[2K"
CLEAR_TO_EOL = "\033[K"
CURSOR_HOME = "\033[H"

try:  # POSIX only; guarded so the module imports on Windows too.
    import termios
    import tty

    _HAVE_TERMIOS = True
except ImportError:  # pragma: no cover - platform dependent
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]
    _HAVE_TERMIOS = False


def move_cursor(row: int = 1, col: int = 1) -> str:
    """ANSI sequence to move the cursor to a 1-indexed ``(row, col)``."""

    return f"\033[{row};{col}H"


@dataclass(frozen=True, slots=True)
class TerminalSize:
    """Detected terminal dimensions in character cells."""

    columns: int
    rows: int


def get_terminal_size(fallback: tuple[int, int] = (80, 24)) -> TerminalSize:
    """Best-effort terminal size, falling back to ``fallback`` (cols, rows)."""

    size = shutil.get_terminal_size(fallback=fallback)
    return TerminalSize(columns=size.columns, rows=size.lines)


@dataclass(frozen=True, slots=True)
class ResolvedWidth:
    """Outcome of :func:`resolve_width`."""

    width: int
    clamped_to_terminal: bool


def resolve_width(
    requested: int | None,
    *,
    terminal_columns: int | None = None,
    margin: int = WIDTH_SAFETY_MARGIN,
    max_width: int = MAX_WIDTH,
    min_width: int = MIN_WIDTH,
) -> ResolvedWidth:
    """Turn an optional ``--width`` into a concrete, terminal-safe value.

    ``None`` means "use the terminal width minus a safety margin". Any value is
    clamped to ``[min_width, max_width]`` and to the visible terminal width so
    playback never causes horizontal scrolling.
    """

    columns = (
        terminal_columns
        if terminal_columns is not None
        else get_terminal_size().columns
    )
    terminal_budget = max(min_width, min(columns - margin, max_width))

    if requested is None:
        return ResolvedWidth(width=terminal_budget, clamped_to_terminal=False)

    target = max(min_width, min(requested, max_width))
    if target > terminal_budget:
        return ResolvedWidth(width=terminal_budget, clamped_to_terminal=True)
    return ResolvedWidth(width=target, clamped_to_terminal=False)


class TerminalController:
    """Own the terminal for the duration of playback."""

    def __init__(
        self,
        out: IO[str] | None = None,
        stdin: IO[str] | None = None,
    ) -> None:
        self._out: IO[str] = out if out is not None else sys.stdout
        self._in: IO[str] = stdin if stdin is not None else sys.stdin
        self._fd: int | None = None
        self._saved_attrs: list | None = None  # type: ignore[type-arg]

    # -- lifecycle ---------------------------------------------------------
    @property
    def interactive(self) -> bool:
        """True when keyboard controls can be read from a real TTY."""

        return self._fd is not None

    def __enter__(self) -> TerminalController:
        with suppress(OSError, ValueError):
            self._out.write(HIDE_CURSOR + CLEAR_SCREEN + CURSOR_HOME)
            self._out.flush()

        if _HAVE_TERMIOS and self._stdin_is_tty():
            with suppress(Exception):
                fd = self._in.fileno()
                self._saved_attrs = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                self._fd = fd
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None and self._saved_attrs is not None:
            with suppress(Exception):
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_attrs)
        self._fd = None
        self._saved_attrs = None
        with suppress(OSError, ValueError):
            self._out.write(RESET + SHOW_CURSOR + "\n")
            self._out.flush()

    # -- drawing ---------------------------------------------------------
    def clear(self) -> None:
        with suppress(OSError, ValueError):
            self._out.write(CLEAR_SCREEN + CURSOR_HOME)
            self._out.flush()

    def draw(self, frame: str, *, status: str | None = None, rows: int | None = None) -> None:
        """Repaint the screen in place with a single buffered write.

        Every rendered line is terminated with an erase-to-EOL so a narrower
        frame never leaves stale characters behind.
        """

        body = frame.replace("\n", CLEAR_TO_EOL + "\n") + CLEAR_TO_EOL
        buffer = CURSOR_HOME + body
        if status is not None:
            anchor = (rows + 2) if rows is not None else 999
            buffer += "\n" + move_cursor(anchor, 1) + CLEAR_LINE + status
        with suppress(OSError, ValueError):
            self._out.write(buffer)
            self._out.flush()

    # -- input ---------------------------------------------------------
    def read_key(self, timeout: float = 0.0) -> str | None:
        """Return one pending keypress, or ``None`` if nothing is buffered.

        Escape sequences (arrow keys etc.) are drained and reported as an empty
        string so callers can ignore them without blocking.
        """

        if self._fd is None:
            return None
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return None
        try:
            data = os.read(self._fd, 1)
        except OSError:  # pragma: no cover - device went away
            return None
        if not data:
            return None
        if data == b"\x1b":
            # Consume the rest of a CSI sequence and ignore it.
            with suppress(OSError):
                while select.select([self._fd], [], [], 0)[0]:
                    os.read(self._fd, 1)
            return ""
        return data.decode("utf-8", errors="ignore")

    # -- internals ---------------------------------------------------------
    def _stdin_is_tty(self) -> bool:
        try:
            return bool(self._in.isatty())
        except (OSError, ValueError):  # pragma: no cover - detached stream
            return False
