"""Tests for yt2ascii.audio."""

from __future__ import annotations

import signal
import subprocess

import pytest

from yt2ascii import audio
from yt2ascii.audio import AudioPlayer, find_player


class FakeProc:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        if sig == getattr(signal, "SIGSTOP", -999):
            self._stopped = True

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


def test_find_player_none_when_nothing_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
    assert find_player() is None


def test_find_player_prefers_first_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audio.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "mpv" else None
    )
    found = find_player()
    assert found is not None
    assert found[0] == "/usr/bin/mpv"


def test_unavailable_player_is_inert() -> None:
    player = AudioPlayer("x.m4a", command=None)
    assert player.available is False
    assert player.player_name is None
    player.start()
    player.pause()
    player.resume()
    player.stop()  # must not raise


def test_start_spawns_with_fixed_argv(spawned: list[FakeProc]) -> None:
    player = AudioPlayer("/tmp/a.m4a", command=("/usr/bin/afplay", ()))
    player.start()
    player.start()  # idempotent
    assert len(spawned) == 1
    assert spawned[0].argv == ["/usr/bin/afplay", "/tmp/a.m4a"]


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="POSIX job control only")
def test_pause_resume_sends_signals(spawned: list[FakeProc]) -> None:
    player = AudioPlayer("/tmp/a.m4a", command=("/usr/bin/afplay", ()))
    player.start()
    player.pause()
    player.pause()  # no double-stop
    player.resume()
    proc = spawned[0]
    assert proc.signals.count(signal.SIGSTOP) == 1
    assert signal.SIGCONT in proc.signals


def test_stop_terminates_and_is_idempotent(spawned: list[FakeProc]) -> None:
    player = AudioPlayer("/tmp/a.m4a", command=("/usr/bin/afplay", ()))
    player.start()
    player.stop()
    player.stop()
    assert spawned[0].terminated is True


def test_stop_kills_on_timeout(spawned: list[FakeProc], monkeypatch: pytest.MonkeyPatch) -> None:
    player = AudioPlayer("/tmp/a.m4a", command=("/usr/bin/afplay", ()))
    player.start()
    proc = spawned[0]

    def raise_timeout(timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(cmd="afplay", timeout=timeout or 0)

    proc.wait = raise_timeout  # type: ignore[method-assign]
    player.stop()
    assert proc.killed is True


def test_context_manager_stops(spawned: list[FakeProc]) -> None:
    with AudioPlayer("/tmp/a.m4a", command=("/usr/bin/afplay", ())) as player:
        player.start()
    assert spawned[0].terminated is True
