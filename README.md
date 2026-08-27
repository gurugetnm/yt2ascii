<!-- markdownlint-disable MD033 MD041 -->
<pre>
      _   ____                  _ _
 _  _| |_|___ \ __ _ ___  ___(_|_)
| || |  _| __) / _` / __|/ __| | |
 \_, |_| / __/ (_| \__ \ (__| | |
 |__/   |_____\__,_|___/\___|_|_|
</pre>

# yt2ascii

> Turn YouTube videos into coloured ASCII art directly in your terminal.

`yt2ascii` downloads a YouTube video, converts every frame into colour ANSI
ASCII art, and plays it back in place inside your terminal, timed to the source
video. The terminal is the entire user interface — there is no web server, no
browser, no database.

---

## Table of contents

1. [Overview](#overview)
2. [Features](#features)
3. [Demo](#demo)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [FFmpeg setup](#ffmpeg-setup)
7. [Usage](#usage)
8. [CLI options](#cli-options)
9. [Examples](#examples)
10. [Architecture](#architecture)
11. [ASCII conversion algorithm](#ascii-conversion-algorithm)
12. [Colour rendering](#colour-rendering)
13. [Performance](#performance)
14. [Terminal compatibility](#terminal-compatibility)
15. [Limitations](#limitations)
16. [Troubleshooting](#troubleshooting)
17. [Future improvements](#future-improvements)
18. [License](#license)

---

## Overview

Given a YouTube URL, `yt2ascii`:

1. Validates the URL.
2. Fetches metadata with `yt-dlp` (title, duration, resolution, source FPS).
3. Checks the duration against a configurable limit.
4. Downloads the video to an isolated temporary directory.
5. Decodes frames with OpenCV, resizing early for speed.
6. Converts each frame to characters (luminance ramp) plus per-cell RGB colour.
7. Emits one ANSI string per frame and repaints the screen in place.
8. Keeps playback timed with a monotonic clock, skipping frames if it falls
   behind.
9. Restores the terminal on quit, `Ctrl+C`, or error, and deletes the temp files.

## Features

- YouTube `watch`, `youtu.be`, and `shorts` URLs.
- 24-bit truecolor, 256-colour, and grayscale rendering modes.
- Automatic terminal-size detection with aspect-ratio correction.
- Monotonic-clock playback scheduler with frame skipping.
- Interactive controls: pause/resume, quit, restart, live width changes.
- Friendly errors for private / deleted / unavailable / age-restricted videos.
- No tracebacks for expected failures; temp files always cleaned up.
- Vectorised NumPy conversion pipeline; a single `write()` per frame.

## Demo

```text
yt2ascii

Video: Big Buck Bunny
Duration: 09:56
Resolution: 1920x1080
Source FPS: 30

Preparing renderer...
✓ ASCII width: 120
✓ Playback FPS: 15
✓ Colour: truecolor

Press SPACE to pause • Q to quit
```

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) on your `PATH` (recommended; see below)
- A terminal that supports ANSI escape sequences (most do)

Python dependencies (installed automatically): `numpy`,
`opencv-python-headless`, `yt-dlp`.

## Installation

```bash
pipx install yt2ascii        # recommended
# or
pip install yt2ascii
```

From a checkout:

```bash
git clone https://github.com/thevinduguruge/yt2ascii
cd yt2ascii
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## FFmpeg setup

`yt-dlp` uses FFmpeg to merge the best video/audio streams, and OpenCV uses the
FFmpeg libraries to decode frames. `yt2ascii` prefers progressive formats so it
can often run without a system FFmpeg, but installing it gives the best quality.

| Platform | Command |
| --- | --- |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` |

## Usage

```bash
yt2ascii "https://www.youtube.com/watch?v=VIDEO_ID"
yt2ascii "https://youtu.be/VIDEO_ID" --width 120
yt2ascii URL --fps 15 --mode truecolor
yt2ascii URL --grayscale
yt2ascii --help
```

## CLI options

| Option | Default | Description |
| --- | --- | --- |
| `--width N` | terminal width | ASCII width in columns (20–200). |
| `--fps N` | `15` | Target playback frames per second (1–60). |
| `--mode MODE` | `truecolor` | `truecolor`, `ansi256`, or `grayscale`. |
| `--chars RAMP` | `" .:-=+*#%@"` | Custom luminance ramp, dark to light. |
| `--grayscale` | off | Shortcut for `--mode grayscale`. |
| `--max-duration S` | `300` | Maximum allowed video length in seconds. |
| `--no-status` | off | Hide the live status line during playback. |
| `--version` | | Print the version and exit. |
| `--help` | | Show help and exit. |

## Examples

```bash
# Wide, high frame-rate, full colour
yt2ascii URL --width 160 --fps 24 --mode truecolor

# Low bandwidth terminal / SSH session
yt2ascii URL --width 80 --fps 10 --mode ansi256

# Monochrome, custom ramp
yt2ascii URL --grayscale --chars " .oO@"

# Allow videos up to 10 minutes
yt2ascii URL --max-duration 600
```

## Architecture

```text
cli.py         argument parsing, pipeline orchestration, friendly errors
config.py      validated Config dataclass + ColorMode
errors.py      Yt2AsciiError hierarchy
youtube.py     URL validation, yt-dlp metadata, temp-dir download
video.py       VideoMetadata, duration checks, OpenCV frame source + sampling
ascii_renderer.py  frame -> characters + dimensions/aspect-ratio maths
color.py       luminance, RGB -> ANSI truecolor / 256 / grayscale
terminal.py    size detection, cursor control, raw-mode key reads, cleanup
player.py      monotonic playback loop, frame skipping, interactive controls
```

Data flow:

```text
YouTube URL -> validate -> yt-dlp metadata -> duration check -> download
           -> OpenCV decode -> resize early -> NumPy luminance + colour
           -> ASCII + ANSI string -> single terminal write -> repeat
```

## ASCII conversion algorithm

For every displayed frame:

1. Decode the frame (BGR) with OpenCV.
2. Convert BGR → RGB.
3. Resize to the target `cols × rows` with `INTER_AREA` (area averaging gives a
   representative colour per cell for free).
4. `rows` is derived from `cols`, the video aspect ratio, and the character cell
   aspect ratio so the image is not stretched.
5. Luminance: `Y = 0.2126R + 0.7152G + 0.0722B`.
6. Normalise `Y` to `0..1` and index into the character ramp
   (`idx = round(Y_norm * (len(ramp) - 1))`), fully vectorised in NumPy.
7. Pair each character with the resized pixel's RGB colour.
8. Build one ANSI string, run-length encoding the colour so unchanged runs share
   a single escape sequence.

## Colour rendering

- **truecolor** — `ESC[38;2;R;G;Bm` per colour run, `ESC[0m` at end of frame.
- **ansi256** — RGB is mapped to the 6×6×6 colour cube or the 24-step grey ramp,
  emitted as `ESC[38;5;Nm`.
- **grayscale** — characters only, no colour escapes.

Colour is per cell: different regions of the frame keep their own colours.

## Performance

- Frames are decoded at source resolution but resized immediately; all heavy
  maths is vectorised NumPy on the small `cols × rows` array.
- The playback scheduler uses target presentation times from a monotonic clock.
  If a frame would be shown too late it is skipped rather than accumulating lag.
- Exactly one buffered `write()` + `flush()` per frame; colour runs are
  RLE-compressed to keep the string short.
- A live status line reports effective FPS, frame index, and width.

## Terminal compatibility

Works in any ANSI-capable terminal (iTerm2, Terminal.app, GNOME Terminal,
Konsole, Windows Terminal, Alacritty, kitty, tmux). Truecolor needs a terminal
with 24-bit colour support; fall back to `--mode ansi256` otherwise. Interactive
controls need a real TTY on stdin.

## Limitations

- No audio playback.
- Video only (no local files / images / webcam yet).
- Very small terminals limit detail.
- Live streams are not supported.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `command not found: ffmpeg` | Install FFmpeg (see above). |
| Colours look wrong / garbled | Use `--mode ansi256` or `--grayscale`. |
| Image looks stretched | Your terminal cell ratio differs; try another font. |
| `Video is unavailable` | Private, deleted, or region-locked video. |
| Playback stutters | Lower `--fps` or `--width`. |
| `This video is age restricted` | Not playable without authentication. |

## Future improvements

Local video files, images and GIFs, webcam and live-stream input, Braille and
Unicode half-block renderers, edge detection, custom palettes, ANSI/asciicast
export, and audio-reactive effects.

## License

[MIT](LICENSE) © Thevindu Guruge
