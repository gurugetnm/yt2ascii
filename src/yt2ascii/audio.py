"""Optional audio playback via an external player process.

yt2ascii never decodes audio itself. It downloads a separate audio-only file to
the session's temporary directory and plays it with whatever lightweight player
is on ``PATH``. The process is always terminated on exit, leaving nothing
behind.

Pause behaviour depends on the player:

* **Seekable** players (``mpv``, ``ffplay``, ``vlc``) are stopped on pause and
  relaunched at the exact position on resume, so audio stays in sync.
* **Non-seekable** players (``afplay`` and the raw PCM players) keep playing
  through a visual pause -- freezing them with signals desynchronises the
  playhead on macOS -- and the video fast-forwards to catch up on resume.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

# name -> (fixed args before the file, seek-argument template or None if the
# player cannot start at an offset). Seekable players are listed first so that
# pause/resume works well out of the box when one is installed.
_PLAYERS: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("mpv", ("--no-video", "--really-quiet"), "--start={pos}"),
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet"), "-ss {pos}"),
    ("afplay", (), None),
    ("cvlc", ("--play-and-exit", "--intf", "dummy", "--quiet"), "--start-time={pos}"),
    ("paplay", (), None),
    ("aplay", ("-q",), None),
)

PlayerCommand = tuple[str, tuple[str, ...], str | None]

# Sentinel: "auto-detect a player" vs. an explicit ``None`` meaning "no player".
_AUTO: object = object()


def find_player() -> PlayerCommand | None:
    """Return ``(executable_path, args, seek_template)`` for the first player found."""

    for name, args, seek in _PLAYERS:
        found = shutil.which(name)
        if found:
            return found, args, seek
    return None


class AudioPlayer:
    """Drive an external audio player subprocess for one playback session."""

    def __init__(
        self,
        path: Path | str,
        *,
        command: PlayerCommand | object | None = _AUTO,
    ) -> None:
        self._path = str(path)
        resolved = find_player() if command is _AUTO else command
        self._command: PlayerCommand | None = resolved  # type: ignore[assignment]
        self._proc: subprocess.Popen[bytes] | None = None
        self._resume_pending = False

    @property
    def available(self) -> bool:
        return self._command is not None

    @property
    def seekable(self) -> bool:
        """True if the player can pause/resume at an arbitrary position."""

        return self._command is not None and self._command[2] is not None

    @property
    def player_name(self) -> str | None:
        return Path(self._command[0]).name if self._command else None

    def start(self, position: float = 0.0) -> None:
        """Spawn the player, optionally starting ``position`` seconds in.

        No-op if unavailable or already running.
        """

        if self._command is None or self._proc is not None:
            return
        exe, base_args, seek_template = self._command

        seek_args: list[str] = []
        if position > 0.25 and seek_template is not None:
            seek_args = seek_template.format(pos=f"{position:.3f}").split()

        with contextlib.suppress(OSError):
            self._proc = subprocess.Popen(
                [exe, *seek_args, *base_args, self._path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def pause(self) -> bool:
        """Handle a playback pause.

        Returns ``True`` if the caller must call :meth:`resume` with a position
        (seekable players, which are stopped now). Returns ``False`` if audio is
        deliberately left running through the pause (non-seekable players).
        """

        if not self.seekable:
            return False
        self.stop()
        self._resume_pending = True
        return True

    def resume(self, position: float = 0.0) -> None:
        """Relaunch a seekable player at ``position`` after a pause."""

        if self._resume_pending:
            self._resume_pending = False
            self.start(position=position)

    def stop(self) -> None:
        """Terminate the player and reap it. Safe to call repeatedly."""

        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1.0)

    def __enter__(self) -> AudioPlayer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
