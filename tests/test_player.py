"""Tests for yt2ascii.player."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from yt2ascii.ascii_renderer import AsciiRenderer
from yt2ascii.config import ColorMode, Config
from yt2ascii.player import Player
from yt2ascii.video import Frame, VideoMetadata


class FakeSource:
    def __init__(self, n: int, *, width: int = 64, height: int = 36, fps: float = 30.0) -> None:
        self._n = n
        self.width = width
        self.height = height
        self.source_fps = fps
        self.resets = 0

    def frames(self, target_fps: float) -> Iterator[Frame]:
        for i in range(self._n):
            img = np.full((self.height, self.width, 3), (i * 7) % 256, dtype=np.uint8)
            yield Frame(index=i, timestamp=i / target_fps, image=img)

    def estimated_output_frames(self, target_fps: float) -> int:
        return self._n

    def reset(self) -> None:
        self.resets += 1


class FakeTerminal:
    def __init__(self, keys: list[str | None] | None = None) -> None:
        self._keys = list(keys or [])
        self.draws: list[tuple[str, str | None]] = []
        self.clears = 0

    def read_key(self, timeout: float = 0.0) -> str | None:
        return self._keys.pop(0) if self._keys else None

    def draw(self, frame: str, *, status: str | None = None, rows: int | None = None) -> None:
        self.draws.append((frame, status))

    def clear(self) -> None:
        self.clears += 1


class RaisingTerminal(FakeTerminal):
    def read_key(self, timeout: float = 0.0) -> str | None:
        raise KeyboardInterrupt


class FakeAudio:
    def __init__(self, *, seekable: bool = True) -> None:
        self.events: list[str] = []
        self.seekable = seekable
        self.resume_positions: list[float] = []

    def start(self, position: float = 0.0) -> None:
        self.events.append("start")

    def pause(self) -> bool:
        self.events.append("pause")
        return self.seekable

    def resume(self, position: float = 0.0) -> None:
        self.events.append("resume")
        self.resume_positions.append(position)

    def stop(self) -> None:
        self.events.append("stop")


META = VideoMetadata(title="t", duration=1.0, width=64, height=36, fps=30.0)


def _player(source: FakeSource, terminal: FakeTerminal, **overrides: object) -> Player:
    config = Config(width=40, fps=10, mode=ColorMode.GRAYSCALE).with_width(40)
    renderer = AsciiRenderer(config)
    kwargs: dict[str, object] = {
        "clock": lambda: 0.0,
        "sleep": lambda _s: None,
        "terminal_rows": 40,
    }
    kwargs.update(overrides)
    return Player(
        source,  # type: ignore[arg-type]
        renderer,
        terminal,  # type: ignore[arg-type]
        config,
        META,
        **kwargs,  # type: ignore[arg-type]
    )


def test_plays_every_frame_when_on_schedule() -> None:
    source = FakeSource(12)
    terminal = FakeTerminal()
    result = _player(source, terminal).run()
    assert result.frames_shown == 12
    assert result.frames_skipped == 0
    assert result.quit_early is False
    assert len(terminal.draws) == 12


def test_q_key_quits_early() -> None:
    source = FakeSource(50)
    terminal = FakeTerminal(keys=["q"])
    result = _player(source, terminal).run()
    assert result.quit_early is True
    assert result.frames_shown == 0


def test_pause_then_resume_completes() -> None:
    source = FakeSource(5)
    terminal = FakeTerminal(keys=[None, " ", " "])  # play, pause, resume
    result = _player(source, terminal).run()
    assert result.quit_early is False
    assert result.frames_shown == 5
    assert any(status == "PAUSED — SPACE resume • Q quit" for _f, status in terminal.draws)


def test_pause_then_quit() -> None:
    source = FakeSource(5)
    terminal = FakeTerminal(keys=[" ", "q"])
    result = _player(source, terminal).run()
    assert result.quit_early is True


def test_width_controls_adjust_dimensions_and_clear() -> None:
    source = FakeSource(3)
    terminal = FakeTerminal(keys=["+"])
    player = _player(source, terminal)
    before = player.dimensions.cols
    player.run()
    assert player.dimensions.cols == before + 4
    assert terminal.clears == 1


def test_fill_stretches_to_terminal_height() -> None:
    source = FakeSource(2, width=1920, height=816)
    terminal = FakeTerminal()
    config = Config(width=40, fps=10, mode=ColorMode.GRAYSCALE, fill=True).with_width(40)
    player = Player(
        source,  # type: ignore[arg-type]
        AsciiRenderer(config),
        terminal,  # type: ignore[arg-type]
        config,
        META,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        terminal_rows=40,
    )
    assert player.dimensions.rows == 38  # terminal_rows - status reserve
    player.run()


def test_no_status_reclaims_a_row() -> None:
    source = FakeSource(1, width=1920, height=816)
    config = Config(width=40, fps=10, mode=ColorMode.GRAYSCALE, fill=True).with_width(40)
    player = Player(
        source,  # type: ignore[arg-type]
        AsciiRenderer(config),
        FakeTerminal(),  # type: ignore[arg-type]
        config,
        META,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        terminal_rows=40,
        show_status=False,
    )
    assert player.dimensions.rows == 39  # only 1 row reserved without the status line


def test_restart_rewinds_source() -> None:
    source = FakeSource(3)
    terminal = FakeTerminal(keys=["r"])
    result = _player(source, terminal).run()
    assert source.resets == 1
    assert result.restarts == 1
    assert result.frames_shown == 3


def test_frame_skipping_when_behind() -> None:
    source = FakeSource(20)
    terminal = FakeTerminal()
    # Clock jumps far ahead on every call: every frame is "late".
    ticks = iter(range(0, 100_000, 100))
    result = _player(source, terminal, clock=lambda: float(next(ticks))).run()
    assert result.frames_skipped > 0
    assert result.frames_shown < 20
    # The final frame is always allowed through.
    assert result.frames_shown >= 1


def test_status_line_contains_metrics() -> None:
    source = FakeSource(2)
    terminal = FakeTerminal()
    _player(source, terminal).run()
    statuses = [s for _f, s in terminal.draws if s]
    assert statuses
    assert "FPS:" in statuses[0]
    assert "Width: 40" in statuses[0]


def test_show_status_false_suppresses_status() -> None:
    source = FakeSource(2)
    terminal = FakeTerminal()
    _player(source, terminal, show_status=False).run()
    assert all(status is None for _f, status in terminal.draws)


def test_audio_starts_and_stops_around_playback() -> None:
    audio = FakeAudio()
    result = _player(FakeSource(4), FakeTerminal(), audio=audio).run()
    assert result.frames_shown == 4
    assert audio.events[0] == "start"
    assert audio.events[-1] == "stop"
    assert audio.events.count("start") == 1


def test_audio_pauses_and_resumes_with_video() -> None:
    audio = FakeAudio(seekable=True)
    terminal = FakeTerminal(keys=[None, " ", " "])
    _player(FakeSource(3), terminal, audio=audio).run()
    assert "pause" in audio.events
    assert audio.events.index("pause") < audio.events.index("resume")


def test_non_seekable_audio_still_gets_resume_call() -> None:
    audio = FakeAudio(seekable=False)
    terminal = FakeTerminal(keys=[None, " ", " "])
    result = _player(FakeSource(4), terminal, audio=audio).run()
    # resume() is always called; the player just decides not to shift the clock.
    assert "resume" in audio.events
    assert result.frames_shown == 4


def test_audio_restarts_on_r_key() -> None:
    audio = FakeAudio()
    terminal = FakeTerminal(keys=["r"])
    _player(FakeSource(3), terminal, audio=audio).run()
    # start (initial) + stop/start (restart) + stop (end)
    assert audio.events.count("start") == 2
    assert audio.events[-1] == "stop"


def test_audio_stopped_on_keyboard_interrupt() -> None:
    audio = FakeAudio()
    _player(FakeSource(5), RaisingTerminal(), audio=audio).run()
    assert audio.events[-1] == "stop"


def test_keyboard_interrupt_is_clean_quit() -> None:
    source = FakeSource(5)
    terminal = RaisingTerminal()
    result = _player(source, terminal).run()
    assert result.quit_early is True


def test_requires_resolved_width() -> None:
    source = FakeSource(1)
    terminal = FakeTerminal()
    config = Config(fps=10, mode=ColorMode.GRAYSCALE)
    with pytest.raises(ValueError):
        Player(source, AsciiRenderer(config), terminal, config, META)  # type: ignore[arg-type]
