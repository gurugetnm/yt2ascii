"""Optional synchronised audio playback via an external player process.

yt2ascii never decodes audio itself. It downloads a separate audio-only file to
the session's temporary directory and plays it with whatever lightweight player
is on ``PATH``. The process is paused/resumed in lock-step with the video and is
always terminated on exit, leaving nothing behind.
"""

from __future__ import annotations

import contextlib
import shutil
import signal
import subprocess
from pathlib import Path

# Player executable -> fixed arguments that precede the file path. Ordered by
# preference; the first one found on PATH wins.
_PLAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("afplay", ()),
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
    ("mpv", ("--no-video", "--really-quiet")),
    ("cvlc", ("--play-and-exit", "--intf", "dummy", "--quiet")),
    ("paplay", ()),
    ("aplay", ("-q",)),
)

_SIGSTOP = getattr(signal, "SIGSTOP", None)
_SIGCONT = getattr(signal, "SIGCONT", None)

# Sentinel: "auto-detect a player" vs. an explicit ``None`` meaning "no player".
_AUTO: object = object()


def find_player() -> tuple[str, tuple[str, ...]] | None:
    """Return ``(executable_path, args)`` for the first available player."""

    for name, args in _PLAYERS:
        found = shutil.which(name)
        if found:
            return found, args
    return None


class AudioPlayer:
    """Drive an external audio player subprocess, synced to video playback."""

    def __init__(
        self,
        path: Path | str,
        *,
        command: tuple[str, tuple[str, ...]] | object | None = _AUTO,
    ) -> None:
        self._path = str(path)
        resolved = find_player() if command is _AUTO else command
        self._command: tuple[str, tuple[str, ...]] | None = resolved  # type: ignore[assignment]
        self._proc: subprocess.Popen[bytes] | None = None
        self._paused = False

    @property
    def available(self) -> bool:
        return self._command is not None

    @property
    def player_name(self) -> str | None:
        return Path(self._command[0]).name if self._command else None

    def start(self) -> None:
        """Spawn the player. No-op if unavailable or already running."""

        if self._command is None or self._proc is not None:
            return
        exe, args = self._command
        with contextlib.suppress(OSError):
            self._proc = subprocess.Popen(
                [exe, *args, self._path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self._paused = False

    def pause(self) -> None:
        if _SIGSTOP is None or self._paused:
            return
        proc = self._proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(OSError, ValueError):
                proc.send_signal(_SIGSTOP)
                self._paused = True

    def resume(self) -> None:
        if not self._paused:
            return
        proc = self._proc
        if proc is not None and proc.poll() is None and _SIGCONT is not None:
            with contextlib.suppress(OSError, ValueError):
                proc.send_signal(_SIGCONT)
        self._paused = False

    def stop(self) -> None:
        """Terminate the player and reap it. Safe to call repeatedly."""

        proc, self._proc = self._proc, None
        self._paused = False
        if proc is None or proc.poll() is not None:
            return
        if _SIGCONT is not None:
            with contextlib.suppress(OSError, ValueError):
                proc.send_signal(_SIGCONT)  # can't kill a stopped process cleanly
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
