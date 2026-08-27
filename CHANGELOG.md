# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-28

First release.

### Added

- `yt2ascii URL` — play a YouTube video as coloured ASCII art in the terminal.
- URL handling: `watch`, `youtu.be`, `shorts`, `embed`, `live`, scheme-less
  URLs, and bare 11-character video ids; playlist/radio query params are
  stripped to the canonical `watch?v=ID`.
- Metadata via `yt-dlp` (title, duration, resolution, source FPS) with a
  configurable duration limit (`--max-duration`, default 300 s).
- Rendering modes: 24-bit `truecolor` (default), `ansi256`, and `grayscale`,
  with a customisable luminance ramp (`--chars`).
- Aspect-ratio-corrected sizing that auto-fits the terminal, `--width` override
  (20–400 columns), and `--fill` to stretch to the whole terminal.
- Monotonic-clock playback scheduler with frame skipping when behind.
- Synced audio playback through an external player (`mpv`, `ffplay`, `vlc`,
  `afplay`, …); seekable players get true pause/resume, `afplay` plays through
  a pause while the video catches up. `--no-audio` to disable.
- Interactive controls: `SPACE` pause/resume, `Q`/`Ctrl+C` quit, `R` restart,
  `+`/`-` live width changes. `--no-status` hides the status line.
- Friendly, traceback-free errors for invalid/private/deleted/unavailable/
  age-restricted/region-locked videos and network failures.
- Strict cleanup: all media lives in a temp dir removed on every exit path; the
  audio process is always terminated; the `yt-dlp` cache is disabled.
- `certifi` dependency so HTTPS works on stock macOS Python.
- Test suite (144 tests), `ruff`, and strict `mypy`, all passing.

[0.1.0]: https://github.com/gurugetnm/yt2ascii/releases/tag/v0.1.0
