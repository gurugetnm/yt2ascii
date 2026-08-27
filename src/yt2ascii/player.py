"""Interactive playback loop: scheduling, frame skipping, and controls."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .ascii_renderer import AsciiRenderer, Dimensions, compute_dimensions
from .audio import AudioPlayer
from .config import MAX_WIDTH, MIN_WIDTH, Config
from .terminal import TerminalController, get_terminal_size
from .video import FrameSource, VideoMetadata

Clock = Callable[[], float]
Sleep = Callable[[float], None]

CONTROLS_HINT = "SPACE pause • Q quit • R restart • +/- width"
_PAUSE_HINT = "PAUSED — SPACE resume • Q quit"

#: Rows kept free below the image for the status line (or 1 spare row without it).
_STATUS_RESERVE = 2
_NO_STATUS_RESERVE = 1


@dataclass(slots=True)
class PlaybackResult:
    """Summary of a completed (or interrupted) playback session."""

    frames_shown: int
    frames_skipped: int
    restarts: int
    quit_early: bool
    effective_fps: float


class Player:
    """Drive a :class:`FrameSource` through a :class:`TerminalController`."""

    def __init__(
        self,
        source: FrameSource,
        renderer: AsciiRenderer,
        terminal: TerminalController,
        config: Config,
        metadata: VideoMetadata,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        show_status: bool = True,
        terminal_rows: int | None = None,
        audio: AudioPlayer | None = None,
    ) -> None:
        if config.width is None:
            raise ValueError("Config.width must be resolved before playback")

        self._source = source
        self._renderer = renderer
        self._terminal = terminal
        self._config = config
        self._clock = clock
        self._sleep = sleep
        self._show_status = show_status
        self._audio = audio

        self._frame_w = source.width or metadata.width or 16
        self._frame_h = source.height or metadata.height or 9
        rows = terminal_rows if terminal_rows is not None else get_terminal_size().rows
        reserve = _STATUS_RESERVE if show_status else _NO_STATUS_RESERVE
        self._max_rows = max(1, rows - reserve)
        self._width = config.width
        self._dims = self._compute_dims()
        self._last_ascii = ""

    # -- public API ------------------------------------------------------
    def run(self) -> PlaybackResult:
        shown = skipped = restarts = 0
        quit_early = False
        dt = 1.0 / self._config.fps
        total = self._source.estimated_output_frames(self._config.fps)

        frames = self._source.frames(self._config.fps)
        start = self._clock()
        fps_ema = float(self._config.fps)
        last_tick = start
        last_index = 0
        if self._audio is not None:
            self._audio.start()

        try:
            while True:
                action = self._poll()
                if action == "quit":
                    quit_early = True
                    break
                if action == "pause":
                    # Seekable players stop now and re-seek on resume, so the
                    # video timeline is shifted by the pause duration. A
                    # non-seekable player (afplay) keeps playing, so we leave
                    # the timeline alone and let the video skip forward to it.
                    audio_held = self._audio is not None and self._audio.pause()
                    paused_for, want_quit = self._pause()
                    if self._audio is not None:
                        self._audio.resume(position=last_index * dt)
                    if self._audio is None or audio_held:
                        start += paused_for
                    last_tick = self._clock()
                    if want_quit:
                        quit_early = True
                        break
                elif action == "restart":
                    restarts += 1
                    self._source.reset()
                    frames = self._source.frames(self._config.fps)
                    if self._audio is not None:
                        self._audio.stop()
                        self._audio.start()
                    self._terminal.clear()
                    start = self._clock()
                    last_tick = start
                    shown = skipped = 0
                    last_index = 0
                    continue
                elif action in ("wider", "narrower"):
                    if self._adjust_width(4 if action == "wider" else -4):
                        self._terminal.clear()

                frame = next(frames, None)
                if frame is None:
                    break
                last_index = frame.index

                target = start + frame.index * dt
                now = self._clock()
                if now - target > dt and frame.index + 1 < total:
                    # More than a whole frame late: drop this one.
                    skipped += 1
                    continue

                wait = target - now
                if wait > 0:
                    self._sleep(min(wait, 1.0))

                self._last_ascii = self._renderer.render(frame.image, self._dims)
                status = (
                    self._status_line(shown + 1, total, fps_ema)
                    if self._show_status
                    else None
                )
                self._terminal.draw(self._last_ascii, status=status, rows=self._dims.rows)
                shown += 1

                tick = self._clock()
                instant = 1.0 / max(1e-6, tick - last_tick)
                fps_ema = 0.85 * fps_ema + 0.15 * instant
                last_tick = tick
        except KeyboardInterrupt:
            quit_early = True
        finally:
            if self._audio is not None:
                self._audio.stop()

        elapsed = max(1e-6, self._clock() - start)
        return PlaybackResult(
            frames_shown=shown,
            frames_skipped=skipped,
            restarts=restarts,
            quit_early=quit_early,
            effective_fps=shown / elapsed,
        )

    @property
    def dimensions(self) -> Dimensions:
        return self._dims

    # -- helpers -------------------------------------------------------
    def _compute_dims(self) -> Dimensions:
        return compute_dimensions(
            self._frame_w,
            self._frame_h,
            self._width,
            cell_aspect_ratio=self._config.cell_aspect_ratio,
            max_height=self._max_rows,
            fill_height=self._max_rows if self._config.fill else None,
        )

    def _adjust_width(self, delta: int) -> bool:
        new_width = max(MIN_WIDTH, min(MAX_WIDTH, self._width + delta))
        if new_width == self._width:
            return False
        self._width = new_width
        self._dims = self._compute_dims()
        return True

    def _poll(self) -> str | None:
        key = self._terminal.read_key(0.0)
        if not key:
            return None
        if key == " ":
            return "pause"
        return {
            "q": "quit",
            "r": "restart",
            "+": "wider",
            "=": "wider",
            "-": "narrower",
            "_": "narrower",
        }.get(key.lower())

    def _pause(self) -> tuple[float, bool]:
        pause_start = self._clock()
        self._terminal.draw(self._last_ascii, status=_PAUSE_HINT, rows=self._dims.rows)
        while True:
            key = self._terminal.read_key(0.05)
            if key is None or key == "":
                continue
            if key == " ":
                return self._clock() - pause_start, False
            if key.lower() == "q":
                return self._clock() - pause_start, True

    def _status_line(self, frame_no: int, total: int, fps_ema: float) -> str:
        total_label = str(total) if total > 0 else "?"
        return (
            f"FPS: {fps_ema:4.1f} | Frame: {frame_no}/{total_label} "
            f"| Width: {self._width}    {CONTROLS_HINT}"
        )
