"""Tests for yt2ascii.audio."""

from __future__ import annotations

import subprocess

import pytest

from yt2ascii import audio
from yt2ascii.audio import AudioPlayer, find_player

_SEEKABLE = ("/usr/bin/mpv", ("--no-video", "--really-quiet"), "--start={pos}")
_FFPLAY = ("/usr/bin/ffplay", ("-nodisp",), "-ss {pos}")
_AFPLAY = ("/usr/bin/afplay", (), None)


class FakeProc:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.terminated = False
        self.killed = False
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        self._alive = False
        return 0


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[FakeProc]:
    procs: list[FakeProc] = []

    def fake_popen(argv: list[str], **_kw: object) -> FakeProc:
        proc = FakeProc(argv)
        procs.append(proc)
        return proc

    monkeypatch.setattr(audio.subprocess, "Popen", fake_popen)
    return procs


class TestFindPlayer:
    def test_none_when_nothing_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
        assert find_player() is None

    def test_prefers_seekable_player_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            audio.shutil,
            "which",
            lambda name: f"/usr/bin/{name}" if name in {"mpv", "afplay"} else None,
        )
        found = find_player()
        assert found is not None
        assert found[0] == "/usr/bin/mpv"
        assert found[2] == "--start={pos}"


class TestUnavailable:
    def test_inert_when_no_player(self) -> None:
        player = AudioPlayer("x.m4a", command=None)
        assert player.available is False
        assert player.seekable is False
        assert player.player_name is None
        player.start()
        assert player.pause() is False
        player.resume(12.0)
        player.stop()  # must not raise


class TestStart:
    def test_start_spawns_once_with_plain_argv(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_AFPLAY)
        player.start()
        player.start()  # idempotent
        assert len(spawned) == 1
        assert spawned[0].argv == ["/usr/bin/afplay", "/tmp/a.m4a"]

    def test_start_injects_seek_for_seekable_player(self, spawned: list[FakeProc]) -> None:
        AudioPlayer("/tmp/a.m4a", command=_SEEKABLE).start(position=42.5)
        assert spawned[0].argv == [
            "/usr/bin/mpv",
            "--start=42.500",
            "--no-video",
            "--really-quiet",
            "/tmp/a.m4a",
        ]

    def test_ffplay_seek_tokens_split(self, spawned: list[FakeProc]) -> None:
        AudioPlayer("/tmp/a.m4a", command=_FFPLAY).start(position=10.0)
        assert spawned[0].argv[:3] == ["/usr/bin/ffplay", "-ss", "10.000"]

    def test_tiny_offset_is_ignored(self, spawned: list[FakeProc]) -> None:
        AudioPlayer("/tmp/a.m4a", command=_SEEKABLE).start(position=0.1)
        assert "--start=0.100" not in spawned[0].argv


class TestPauseResume:
    def test_seekable_pause_stops_and_resume_reseeks(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_SEEKABLE)
        player.start()
        assert player.pause() is True
        assert spawned[0].terminated is True
        player.resume(position=30.0)
        assert len(spawned) == 2
        assert "--start=30.000" in spawned[1].argv

    def test_non_seekable_pause_is_noop(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_AFPLAY)
        player.start()
        assert player.pause() is False
        assert spawned[0].terminated is False  # still playing
        player.resume(position=30.0)
        assert len(spawned) == 1  # not relaunched

    def test_resume_without_pause_does_nothing(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_SEEKABLE)
        player.start()
        player.resume(position=5.0)
        assert len(spawned) == 1


class TestStop:
    def test_terminates_and_idempotent(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_AFPLAY)
        player.start()
        player.stop()
        player.stop()
        assert spawned[0].terminated is True

    def test_kills_on_timeout(self, spawned: list[FakeProc]) -> None:
        player = AudioPlayer("/tmp/a.m4a", command=_AFPLAY)
        player.start()
        proc = spawned[0]

        def raise_timeout(timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="afplay", timeout=timeout or 0)

        proc.wait = raise_timeout  # type: ignore[method-assign]
        player.stop()
        assert proc.killed is True

    def test_context_manager_stops(self, spawned: list[FakeProc]) -> None:
        with AudioPlayer("/tmp/a.m4a", command=_AFPLAY) as player:
            player.start()
        assert spawned[0].terminated is True
