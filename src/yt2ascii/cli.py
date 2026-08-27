"""Command-line entry point and playback pipeline orchestration."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import IO

from . import __version__
from .ascii_renderer import AsciiRenderer
from .audio import AudioPlayer
from .config import (
    DEFAULT_CHARS,
    DEFAULT_FPS,
    DEFAULT_MAX_DURATION,
    MAX_WIDTH,
    ColorMode,
    Config,
)
from .errors import Yt2AsciiError
from .player import Player
from .terminal import TerminalController, get_terminal_size, resolve_width
from .video import FrameSource, VideoMetadata, format_timestamp, validate_duration
from .youtube import download_audio, download_video, extract_metadata, validate_url

_PROG = "yt2ascii"

_EPILOG = """\
examples:
  yt2ascii "https://www.youtube.com/watch?v=VIDEO_ID"
  yt2ascii "https://youtu.be/VIDEO_ID" --width 120
  yt2ascii URL --fps 15 --mode truecolor
  yt2ascii URL --grayscale
  yt2ascii URL --max-duration 600

controls:
  SPACE  pause / resume        Q / Ctrl+C  quit
  R      restart               + / -       change width
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the ``yt2ascii`` command."""

    parser = argparse.ArgumentParser(
        prog=_PROG,
        description="Turn YouTube videos into coloured ASCII art directly in your terminal.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="YouTube video URL (watch, youtu.be, or shorts).")
    parser.add_argument(
        "--width",
        type=int,
        metavar="N",
        default=None,
        help=f"ASCII width in columns (20-{MAX_WIDTH}). Default: fit the terminal.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        metavar="N",
        default=DEFAULT_FPS,
        help=f"Target playback frames per second (1-60). Default: {DEFAULT_FPS}.",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ColorMode],
        default=ColorMode.TRUECOLOR.value,
        help="Colour mode: truecolor, ansi256, or grayscale. Default: truecolor.",
    )
    parser.add_argument(
        "--chars",
        metavar="RAMP",
        default=DEFAULT_CHARS,
        # argparse treats '%' specially in help text, so escape the default ramp.
        help=(
            "Luminance ramp from dark to light. Default: "
            + repr(DEFAULT_CHARS).replace("%", "%%")
            + "."
        ),
    )
    parser.add_argument(
        "--grayscale",
        action="store_true",
        help="Shortcut for --mode grayscale.",
    )
    parser.add_argument(
        "--fill",
        action="store_true",
        help="Stretch the image to fill the whole terminal, ignoring aspect ratio.",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        metavar="SECONDS",
        default=DEFAULT_MAX_DURATION,
        help=f"Maximum allowed video length in seconds. Default: {DEFAULT_MAX_DURATION}.",
    )
    parser.add_argument(
        "--no-status",
        action="store_true",
        help="Hide the live status line during playback.",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Do not download or play the audio track.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{_PROG} {__version__}",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        width=args.width,
        fps=args.fps,
        mode=ColorMode(args.mode),
        chars=args.chars,
        grayscale=args.grayscale,
        max_duration=args.max_duration,
        show_status=not args.no_status,
        fill=args.fill,
        audio=not args.no_audio,
    )


def _echo(out: IO[str], message: str = "") -> None:
    out.write(message + "\n")
    out.flush()


def run_pipeline(
    url: str,
    config: Config,
    *,
    out: IO[str] | None = None,
) -> None:
    """Validate, fetch, download, and play ``url`` as ASCII art.

    Raises :class:`Yt2AsciiError` subclasses for any expected failure; the CLI
    turns those into a friendly one-line message.
    """

    stream = out if out is not None else sys.stdout

    _echo(stream, f"\n{_PROG}\n")
    canonical = validate_url(url)

    if shutil.which("ffmpeg") is None:
        _echo(stream, "note: FFmpeg was not found on PATH; using progressive formats only.\n")

    _echo(stream, "Fetching video information...")
    raw = extract_metadata(canonical)
    metadata = VideoMetadata.from_raw(raw)

    _echo(stream, "✓ Video found")
    _echo(stream, f"✓ Title: {metadata.title}")
    _echo(stream, f"✓ Duration: {format_timestamp(metadata.duration)}")
    _echo(stream, f"✓ Resolution: {metadata.resolution_label}")
    _echo(stream, f"✓ Source FPS: {metadata.fps_label}")

    validate_duration(metadata.duration, config.max_duration)

    _echo(stream, "\nPreparing renderer...")
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{_PROG}-"))
    source: FrameSource | None = None
    audio: AudioPlayer | None = None
    try:
        video_path = download_video(canonical, temp_dir)
        source = FrameSource(video_path)

        if config.audio:
            audio = _prepare_audio(canonical, temp_dir, stream)

        term_size = get_terminal_size()
        resolved = resolve_width(config.width, terminal_columns=term_size.columns)
        final_config = config.with_width(resolved.width)
        renderer = AsciiRenderer(final_config)

        _echo(stream, f"✓ ASCII width: {resolved.width}")
        if resolved.clamped_to_terminal:
            _echo(stream, "  (clamped to fit the current terminal)")
        _echo(stream, f"✓ Playback FPS: {final_config.fps}")
        _echo(stream, f"✓ Colour: {final_config.effective_mode.value}")
        if audio is not None and audio.available:
            _echo(stream, f"✓ Audio: {audio.player_name}")
        _echo(stream, "\nPress SPACE to pause • Q to quit\n")

        with TerminalController() as terminal:
            player = Player(
                source,
                renderer,
                terminal,
                final_config,
                metadata,
                show_status=final_config.show_status,
                terminal_rows=term_size.rows,
                audio=audio,
            )
            result = player.run()

        _echo(stream)
        summary = (
            f"Played {result.frames_shown} frames "
            f"({result.effective_fps:.1f} fps effective"
        )
        if result.frames_skipped:
            summary += f", {result.frames_skipped} skipped"
        summary += ")."
        _echo(stream, summary)
        if result.quit_early:
            _echo(stream, "Stopped early.")
    finally:
        if audio is not None:
            audio.stop()
        if source is not None:
            source.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def _prepare_audio(url: str, temp_dir: Path, stream: IO[str]) -> AudioPlayer | None:
    """Download the audio track and pick a player, or explain why not."""

    try:
        audio_path = download_audio(url, temp_dir)
    except Yt2AsciiError as exc:
        _echo(stream, f"note: audio unavailable ({exc}); playing silently.")
        return None

    player = AudioPlayer(audio_path)
    if not player.available:
        _echo(
            stream,
            "note: no audio player found (install ffmpeg/mpv, or use afplay on "
            "macOS); playing silently.",
        )
        return None
    return player


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = _config_from_args(args)
        run_pipeline(args.url, config)
    except Yt2AsciiError as exc:
        print(f"\nError: {exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
