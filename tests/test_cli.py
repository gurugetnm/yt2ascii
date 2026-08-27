"""Tests for yt2ascii.cli."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from yt2ascii import __version__, cli
from yt2ascii.player import PlaybackResult
from yt2ascii.terminal import TerminalSize
from yt2ascii.youtube import RawMetadata

VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _raw(duration: float = 100.0) -> RawMetadata:
    return RawMetadata(
        video_id="dQw4w9WgXcQ",
        title="Example Video",
        duration=duration,
        width=1920,
        height=1080,
        fps=30.0,
        webpage_url=VALID_URL,
    )


class _FakeSource:
    width = 1920
    height = 1080

    def __init__(self, *_a: object, **_k: object) -> None: ...

    def close(self) -> None: ...


class _FakeTerminal:
    def __init__(self, *_a: object, **_k: object) -> None: ...

    def __enter__(self) -> _FakeTerminal:
        return self

    def __exit__(self, *_exc: object) -> None: ...


class _FakePlayer:
    def __init__(self, *_a: object, **_k: object) -> None: ...

    def run(self) -> PlaybackResult:
        return PlaybackResult(
            frames_shown=42,
            frames_skipped=3,
            restarts=0,
            quit_early=False,
            effective_fps=14.6,
        )


class _FakeAudio:
    available = False
    seekable = False
    player_name = None

    def __init__(self, *_a: object, **_k: object) -> None: ...

    def stop(self) -> None: ...


@pytest.fixture
def happy_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "extract_metadata", lambda _url: _raw())
    monkeypatch.setattr(cli, "download_video", lambda _url, _dir: Path(_dir) / "v.mp4")
    monkeypatch.setattr(cli, "download_audio", lambda _url, _dir: Path(_dir) / "a.m4a")
    monkeypatch.setattr(cli, "AudioPlayer", _FakeAudio)
    monkeypatch.setattr(cli, "FrameSource", _FakeSource)
    monkeypatch.setattr(cli, "TerminalController", _FakeTerminal)
    monkeypatch.setattr(cli, "Player", _FakePlayer)
    monkeypatch.setattr(cli, "get_terminal_size", lambda *a, **k: TerminalSize(120, 40))
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/ffmpeg")


class TestParser:
    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "usage:" in out
        assert "--grayscale" in out
        assert "examples:" in out

    def test_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_invalid_mode_is_argparse_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main([VALID_URL, "--mode", "sepia"])
        assert exc.value.code == 2

    def test_defaults(self) -> None:
        args = cli.build_parser().parse_args([VALID_URL])
        assert args.fps == 15
        assert args.mode == "truecolor"
        assert args.width is None
        assert args.fill is False

    def test_fill_flag(self) -> None:
        args = cli.build_parser().parse_args([VALID_URL, "--fill"])
        assert args.fill is True
        assert cli._config_from_args(args).fill is True

    def test_no_audio_flag(self) -> None:
        assert cli._config_from_args(cli.build_parser().parse_args([VALID_URL])).audio is True
        args = cli.build_parser().parse_args([VALID_URL, "--no-audio"])
        assert cli._config_from_args(args).audio is False


class TestMainErrors:
    def test_invalid_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["not-a-youtube-url"]) == 1
        assert "Error:" in capsys.readouterr().err

    def test_invalid_width(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([VALID_URL, "--width", "3"]) == 1
        assert "width" in capsys.readouterr().err.lower()

    def test_invalid_fps(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([VALID_URL, "--fps", "0"]) == 1
        assert "fps" in capsys.readouterr().err.lower()

    def test_empty_chars(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([VALID_URL, "--chars", "x"]) == 1
        assert "chars" in capsys.readouterr().err.lower()

    def test_duration_limit(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli, "extract_metadata", lambda _url: _raw(duration=763))
        monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
        assert cli.main([VALID_URL, "--max-duration", "300"]) == 1
        err = capsys.readouterr().err
        assert "Maximum allowed duration" in err

    def test_keyboard_interrupt_returns_130(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_url: str) -> RawMetadata:
            raise KeyboardInterrupt

        monkeypatch.setattr(cli, "extract_metadata", boom)
        monkeypatch.setattr(cli.shutil, "which", lambda _name: "x")
        assert cli.main([VALID_URL]) == 130


class TestHappyPath:
    def test_full_run(
        self, happy_pipeline: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main([VALID_URL, "--width", "100", "--fps", "15"]) == 0
        out = capsys.readouterr().out
        assert "Example Video" in out
        assert "ASCII width: 100" in out
        assert "Played 42 frames" in out
        assert "3 skipped" in out

    def test_grayscale_flag(self, happy_pipeline: None, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([VALID_URL, "--grayscale"]) == 0
        assert "Colour: grayscale" in capsys.readouterr().out

    def test_temp_dir_is_cleaned_up(
        self, monkeypatch: pytest.MonkeyPatch, happy_pipeline: None
    ) -> None:
        created: list[Path] = []
        real_mkdtemp = cli.tempfile.mkdtemp

        def tracking_mkdtemp(*a: object, **k: object) -> str:
            path = real_mkdtemp(*a, **k)
            created.append(Path(path))
            return path

        monkeypatch.setattr(cli.tempfile, "mkdtemp", tracking_mkdtemp)
        cli.main([VALID_URL])
        assert created and not created[0].exists()

    def test_writes_to_provided_stream(self, happy_pipeline: None) -> None:
        buffer = io.StringIO()
        cli.run_pipeline(VALID_URL, cli.Config(width=80), out=buffer)
        assert "yt2ascii" in buffer.getvalue()

    def test_no_audio_skips_audio_download(
        self, happy_pipeline: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            cli, "download_audio", lambda _u, _d: calls.append("x") or Path("a")
        )
        cli.main([VALID_URL, "--no-audio"])
        assert calls == []

    def test_missing_audio_player_notes_silent_playback(
        self, happy_pipeline: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # _FakeAudio.available is False -> the pipeline should say so and go on.
        assert cli.main([VALID_URL]) == 0
        assert "playing silently" in capsys.readouterr().out
