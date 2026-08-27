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
ASCII art, plays it back in place inside your terminal (timed to the source),
and plays the audio alongside it. The terminal is the entire user interface —
there is no web server, no browser, no database, and nothing is left on disk
after it exits.

---

## Table of contents

1. [Overview](#overview)
2. [Features](#features)
3. [Demo](#demo)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [FFmpeg setup](#ffmpeg-setup)
7. [Audio setup](#audio-setup)
8. [Usage](#usage)
9. [CLI options](#cli-options)
10. [Examples](#examples)
11. [Playback controls](#playback-controls)
12. [Full-screen playback](#full-screen-playback)
13. [Architecture](#architecture)
14. [ASCII conversion algorithm](#ascii-conversion-algorithm)
15. [Colour rendering](#colour-rendering)
16. [Aspect-ratio correction](#aspect-ratio-correction)
17. [Playback timing](#playback-timing)
18. [Audio synchronisation](#audio-synchronisation)
19. [Temporary files and privacy](#temporary-files-and-privacy)
20. [Performance](#performance)
21. [Terminal compatibility](#terminal-compatibility)
22. [Limitations](#limitations)
23. [Troubleshooting](#troubleshooting)
24. [Development](#development)
25. [Future improvements](#future-improvements)
26. [License](#license)

---

## Overview

Given a YouTube URL, `yt2ascii`:

1. Validates the URL (accepts `watch`, `youtu.be`, `shorts`, `embed`, `live`,
   scheme-less URLs, or a bare 11-character video id).
2. Fetches metadata with `yt-dlp` — title, duration, resolution, source FPS.
3. Checks the duration against a configurable limit (default 5 minutes).
4. Downloads the video, and unless `--no-audio` a separate audio-only track,
   into one isolated temporary directory.
5. Decodes frames with OpenCV, resizing each one down immediately.
6. Converts every displayed frame to characters (luminance ramp) plus per-cell
   RGB colour, fully vectorised in NumPy.
7. Emits one ANSI string per frame and repaints the screen in place — the
   terminal never scrolls.
8. Keeps video timed with a monotonic clock, skipping frames if it falls
   behind; the audio track plays through an external player, paused and resumed
   in lock-step with the video.
9. On quit, `Q`, `Ctrl+C`, or any error: restores the terminal, kills the audio
   process, and deletes the entire temporary directory.

Data flow:

```text
YouTube URL
  -> validate / canonicalise
  -> yt-dlp metadata  -> duration check
  -> download video (+ audio) to a temp dir
  -> OpenCV decode -> resize early -> NumPy luminance + colour
  -> ASCII + ANSI string -> single terminal write ---.
  -> monotonic-clock scheduler (skip if late) -------+--> repeat
  -> external audio player, synced to the clock -----'
  -> on exit: kill audio, rmtree temp dir
```

## Features

- YouTube `watch`, `youtu.be`, `shorts`, `embed`, and `live` URLs; scheme-less
  URLs (`youtube.com/watch?v=...`); or a bare video id.
- Playlist / radio query params (`&list=`, `&index=`, `&pp=`, `&si=`) are
  stripped to the canonical `watch?v=ID`.
- 24-bit **truecolor**, **256-colour**, and **grayscale** rendering modes.
- **Synced audio** via `mpv` / `ffplay` / `vlc` / `afplay` (`--no-audio` mutes);
  `mpv` or `ffmpeg` gives true pause/resume-in-sync.
- Automatic terminal-size detection with **aspect-ratio correction**, or
  `--fill` to stretch to the whole terminal.
- Custom luminance ramp via `--chars`.
- Monotonic-clock playback scheduler with **frame skipping** when behind.
- Interactive controls: pause/resume, quit, restart, live width changes.
- Friendly one-line errors for private / deleted / unavailable / age-restricted
  / region-locked videos, and for network failures — never a Python traceback.
- **Nothing persisted**: all media lives in a temp dir wiped on every exit path,
  and the yt-dlp cache is disabled.
- Vectorised NumPy pipeline; a single buffered `write()` per frame with
  run-length-encoded colour.

## Demo

Pre-flight output before playback starts:

```text
yt2ascii

Fetching video information...
✓ Video found
✓ Title: Big Buck Bunny
✓ Duration: 09:56
✓ Resolution: 1920x1080
✓ Source FPS: 30

Preparing renderer...
✓ ASCII width: 120
✓ Playback FPS: 15
✓ Colour: truecolor
✓ Audio: afplay

Press SPACE to pause • Q to quit
```

During playback the status line (unless `--no-status`) reads:

```text
FPS: 14.8 | Frame: 182/1530 | Width: 120    SPACE pause • Q quit • R restart • +/- width
```

## Requirements

- **Python 3.11+**
- A terminal that supports ANSI escape sequences (virtually all do)
- **FFmpeg** on your `PATH` — optional but recommended (see below)
- **An audio player** on your `PATH` for sound — one of `mpv`, `ffplay`,
  `afplay` (bundled with macOS), `cvlc`/`vlc`, `paplay`, `aplay`. `mpv` or
  `ffmpeg` also enables true pause/resume; `afplay` alone cannot pause. Without
  any player, playback is silent.

Python dependencies, installed automatically: `certifi`, `numpy`,
`opencv-python-headless`, `yt-dlp`.

## Installation

```bash
pipx install yt2ascii        # recommended
# or
pip install yt2ascii
```

From a checkout:

```bash
git clone https://github.com/gurugetnm/yt2ascii
cd yt2ascii
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### macOS: `CERTIFICATE_VERIFY_FAILED`

A python.org build of Python often ships without a CA bundle, so `yt-dlp`
cannot verify HTTPS. `yt2ascii` depends on `certifi` to avoid this, but if you
still hit it, run the certificate installer that ships with Python:

```bash
/Applications/Python\ 3.12/Install\ Certificates.command
```

or, in your environment:

```bash
pip install --upgrade certifi
export SSL_CERT_FILE="$(python -m certifi)"
```

## FFmpeg setup

`yt-dlp` uses FFmpeg to merge separate video/audio streams, and OpenCV uses the
FFmpeg libraries to decode frames. `yt2ascii` deliberately prefers progressive
single-file formats so it can usually run **without** a system FFmpeg, but
installing it unlocks the best source quality.

| Platform | Command |
| --- | --- |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` |

If FFmpeg is missing, `yt2ascii` prints a one-line note and continues.

## Audio setup

Audio is **on by default**. `yt2ascii` downloads a separate audio-only stream
(`bestaudio`, preferring `m4a`) and plays it with the first available player
found on `PATH`, in this order:

`mpv` → `ffplay` → `afplay` → `cvlc` → `paplay` → `aplay`

macOS has `afplay` built in — nothing to install for sound. But `afplay`
**cannot pause mid-file**, so with it a `SPACE` pause keeps the music playing
and the video jumps forward to catch up on resume. Install a seekable player
for true pause/resume:

```bash
brew install mpv            # macOS
sudo apt install mpv        # Debian/Ubuntu (or: ffmpeg, vlc)
```

If no player is found at all, `yt2ascii` prints `note: no audio player found …
playing silently` and plays the video only. Use `--no-audio` to skip the audio
download entirely.

## Usage

```bash
yt2ascii "https://www.youtube.com/watch?v=VIDEO_ID"
yt2ascii "https://youtu.be/VIDEO_ID" --width 120
yt2ascii youtube.com/watch?v=VIDEO_ID            # scheme-less
yt2ascii VIDEO_ID                                # bare id
yt2ascii URL --fps 15 --mode truecolor
yt2ascii URL --grayscale
yt2ascii URL --fill --no-status                  # fill the whole terminal
yt2ascii URL --max-duration 3600                 # allow long videos
yt2ascii --help
```

## CLI options

| Option | Default | Description |
| --- | --- | --- |
| `url` | — | YouTube URL (`watch`, `youtu.be`, `shorts`, `embed`, `live`), scheme-less URL, or bare 11-char video id. |
| `--width N` | fit terminal | ASCII width in columns, `20`–`400`. Default: terminal width minus a small margin. |
| `--fps N` | `15` | Target playback frames per second, `1`–`60`. |
| `--mode MODE` | `truecolor` | `truecolor`, `ansi256`, or `grayscale`. |
| `--chars RAMP` | `" .:-=+*#%@"` | Custom luminance ramp, dark to light (≥ 2 chars). |
| `--grayscale` | off | Shortcut for `--mode grayscale`. |
| `--fill` | off | Stretch the image to fill the whole terminal, ignoring aspect ratio. |
| `--max-duration S` | `300` | Maximum allowed video length in seconds. |
| `--no-audio` | off | Skip the audio download and play silently. |
| `--no-status` | off | Hide the live status line (frees one more row for the image). |
| `--version` | — | Print the version and exit. |
| `--help` | — | Show help with examples and exit. |

Invalid values fail fast with a friendly message, e.g.:

```text
Error: Video duration is 08:29.

Maximum allowed duration is 05:00.

Use --max-duration to change this limit.
```

## Examples

```bash
# Wide, high frame-rate, full colour, with sound
yt2ascii URL --width 200 --fps 24 --mode truecolor

# Fill the terminal, no status line
yt2ascii URL --fill --no-status

# Low-bandwidth SSH session
yt2ascii URL --width 80 --fps 10 --mode ansi256 --no-audio

# Monochrome, custom 5-level ramp
yt2ascii URL --grayscale --chars " .oO@"

# A 12-minute video
yt2ascii URL --max-duration 900
```

## Playback controls

| Key | Action |
| --- | --- |
| `SPACE` | Pause / resume (video **and** audio) |
| `Q` | Quit |
| `Ctrl+C` | Quit |
| `R` | Restart from the beginning |
| `+` / `=` | Increase width by 4 columns |
| `-` / `_` | Decrease width by 4 columns |

Controls require a real TTY on stdin (they are inactive when input is piped).

## Full-screen playback

`yt2ascii` already auto-sizes to your terminal. To make the picture as large as
possible:

1. **Fullscreen the terminal window** — on macOS press `⌃⌘F`.
2. **Shrink the font** a few steps (`⌘ -`). A smaller font means more character
   cells, which means more detail. Width is capped at **400 columns**.
3. **Run with `--fill --no-status`** so every row is used and the aspect ratio
   is stretched to the terminal instead of letter-boxed.

```bash
yt2ascii URL --fill --no-status --max-duration 3600
```

For the intended look, also set your **terminal background to solid black** —
`yt2ascii` colours the characters, not the cell background, so dark parts of the
video show your terminal's background through them.

## Architecture

```text
src/yt2ascii/
  __init__.py        version
  cli.py             argument parsing, pipeline orchestration, friendly errors
  config.py          validated Config dataclass + ColorMode
  errors.py          Yt2AsciiError hierarchy
  youtube.py         URL validation, yt-dlp metadata, temp-dir video/audio download
  video.py           VideoMetadata, duration checks, OpenCV frame source + sampling
  ascii_renderer.py  frame -> characters, dimensions / aspect-ratio maths
  color.py           luminance, RGB -> ANSI truecolor / 256 / grayscale
  terminal.py        size detection, cursor control, raw-mode key reads, cleanup
  audio.py           external-player subprocess: start / pause / resume / stop
  player.py          monotonic playback loop, frame skipping, A/V sync, controls
```

Each module has one job and no framework glue. `cli.run_pipeline()` is the only
place that wires them together.

## ASCII conversion algorithm

For every displayed frame:

1. Decode the frame (BGR) with OpenCV, convert BGR → RGB.
2. Resize to the target `cols × rows` with `INTER_AREA` — area averaging gives a
   representative colour per cell for free.
3. Luminance: `Y = 0.2126·R + 0.7152·G + 0.0722·B` (BT.709), vectorised.
4. Normalise and index into the ramp:
   `idx = round(Y / 255 · (len(ramp) − 1))`, clipped to the ramp bounds.
5. Look up `ramp[idx]` for the whole grid in one NumPy operation.
6. Pair each character with its resized pixel's RGB colour.
7. Build one ANSI string, **run-length encoding** the colour so an unbroken run
   of same-coloured cells shares a single escape sequence.
8. Terminate the frame with `ESC[0m`.

There are no Python loops over individual pixels.

## Colour rendering

Colour is per cell — different regions of the frame keep their own colours.

- **truecolor** — `ESC[38;2;R;G;Bm` before each colour run.
- **ansi256** — RGB is snapped to the xterm 6×6×6 colour cube, or to the 24-step
  grey ramp (indices 232–255) for near-grey pixels, emitted as `ESC[38;5;Nm`.
- **grayscale** — characters only, no colour escapes at all.

Only the **foreground** colour is set; the cell background is left to the
terminal.

## Aspect-ratio correction

Terminal cells are about twice as tall as they are wide. Row count is:

```text
rows = round(cols · (frame_height / frame_width) / cell_aspect_ratio)
```

with `cell_aspect_ratio = 2.0` by default, then clamped so the image never
exceeds the visible terminal height (leaving two rows for the status line).
`--fill` bypasses this and sets `rows` to the full terminal height, stretching
the image.

## Playback timing

The scheduler uses a monotonic clock and fixed target presentation times:
`target(i) = start + i / fps`. For each output frame:

- If the clock is already more than one frame past `target(i)` (and it is not
  the last frame), the frame is **skipped** — rendered work and the terminal
  write are dropped rather than accumulating latency.
- Otherwise it sleeps until `target(i)` (in ≤ 1 s slices), renders, and writes.

When a **seekable** player is in use, pausing shifts `start` by the paused
duration so the video resumes exactly where it froze. With a **non-seekable**
player, `start` is left unchanged and the frame scheduler skips forward to catch
up with the still-running audio.

## Audio synchronisation

The audio file is handed to an external player as a plain argument array (no
shell). Playback starts when the video clock starts, so audio and video are
**start-aligned**. Freezing a player with `SIGSTOP` is *not* used — on macOS
`afplay`'s playhead keeps advancing while stopped, so it would resume near the
end and then fall silent.

| Event | Seekable player (`mpv`, `ffplay`, `vlc`) | Non-seekable (`afplay`, `paplay`, `aplay`) |
| --- | --- | --- |
| **Pause** | player is stopped | player keeps playing |
| **Resume** | relaunched with `--start=` / `-ss` at the current video position | nothing; video fast-forwards to the audio |
| **Restart** | stopped and relaunched from 0 | stopped and relaunched from 0 |
| **Exit** | `SIGTERM`, then `SIGKILL` after 1 s | same |

Seek-based resume is approximate (keyframe granularity for `ffplay`), and
overall sync can drift slightly on very long videos or under heavy frame
skipping. Install `mpv` or `ffmpeg` for the smoothest pause/resume.

## Temporary files and privacy

- All media is written to `tempfile.mkdtemp(prefix="yt2ascii-")` —
  `<id>.video.<ext>` and `<id>.audio.<ext>`.
- `shutil.rmtree(temp_dir)` runs in a `finally` block in `run_pipeline`, so it
  executes on success, `Q`, `Ctrl+C` (`KeyboardInterrupt`), and exceptions.
- The audio subprocess is terminated in a `finally` block in both the player
  and the pipeline.
- yt-dlp's own cache is disabled (`cachedir: False`), so nothing is written to
  `~/.cache/yt-dlp`.
- No configuration or state files are created anywhere.

The only way media survives a run is `SIGKILL` (`kill -9`) or a power loss,
which cannot be trapped; the OS clears the temp directory later regardless.

## Performance

- Frames are decoded at source resolution but resized immediately; all heavy
  maths runs on the small `cols × rows` array.
- Source frames that will not be displayed are *grabbed* (no decode) and
  skipped; only displayed frames are decoded and colour-converted.
- Exactly one buffered `write()` + `flush()` per frame; colour runs are
  RLE-compressed to keep the string short.
- Indicative renderer throughput (worst case — random-noise 720p → 120 cols):

  | Mode | ms/frame | headroom |
  | --- | --- | --- |
  | truecolor | ~5.6 | ~180 fps |
  | ansi256 | ~4.0 | ~250 fps |
  | grayscale | ~3.7 | ~270 fps |

  Real video frames compress far better than noise. If your terminal cannot
  keep up at a large size, lower `--fps` or `--width`.

## Terminal compatibility

Works in any ANSI-capable terminal: iTerm2, Terminal.app, GNOME Terminal,
Konsole, Windows Terminal, Alacritty, kitty, and inside `tmux`. Truecolor needs
24-bit colour support — use `--mode ansi256` or `--grayscale` otherwise.
Interactive controls need a real TTY on stdin. Signal-based audio pause/resume
is POSIX-only; on Windows the audio simply keeps playing while the video is
paused.

## Limitations

- No web UI — the terminal is the whole interface, by design.
- Audio needs an external player on `PATH`. With `afplay` (macOS default) a
  pause does not stop the music — install `mpv` or `ffmpeg` for that. A/V sync
  is start-aligned, not sample-accurate, and can drift on very long videos.
- Video input only — no local files, images, GIFs, or webcam yet.
- Live streams (no fixed duration) are rejected.
- Very small terminals limit detail; the width cap is 400 columns.
- Only the foreground colour is set, so the look depends on your terminal's
  background colour.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `CERTIFICATE_VERIFY_FAILED` | Run Python's *Install Certificates* command, or `pip install certifi` and `export SSL_CERT_FILE=$(python -m certifi)`. |
| `Error: Could not reach YouTube …` | Network/DNS/SSL problem — check connectivity; see the row above. |
| `Error: Video duration is …` | The video exceeds `--max-duration`; pass a larger value. |
| No sound | Install an audio player (`mpv`, `ffmpeg`, `vlc`); macOS already has `afplay`. Check the `✓ Audio:` pre-flight line. |
| Sound gone / silent after a pause | You're on `afplay`, which can't pause mid-file. `brew install mpv` (or `ffmpeg`) for pausable audio. |
| Dark parts aren't black | Set your terminal background to solid black; `yt2ascii` only colours characters, not cell backgrounds. |
| Colours look wrong / garbled | Use `--mode ansi256` or `--grayscale`; your terminal may lack 24-bit colour. |
| Image looks stretched or squashed | Your font's cell ratio differs from 2:1 — try another font, or use `--fill`. |
| Playback stutters | Lower `--fps`, lower `--width`, or increase the terminal font size less aggressively. |
| `Error: This video is unavailable …` | Private, deleted, region-locked, or age-restricted — not playable. |
| `command not found: ffmpeg` note | Optional; install FFmpeg for better source quality. |
| Controls do nothing | stdin is not a TTY (piped input) — run it directly in a terminal. |

## Development

```bash
pip install -e ".[dev]"

pytest          # unit tests (no network; external services are mocked)
ruff check .    # lint
mypy src        # type-check (strict)
```

Tests never download real videos — `yt-dlp`, subprocesses, `cv2.VideoCapture`,
and the terminal are all faked.

## Future improvements

Local video files, images and GIFs, webcam and live-stream input, per-cell
background colour, Braille and Unicode half-block renderers, edge detection,
custom palettes, ANSI / asciicast export, and audio-reactive effects.

## License

[MIT](LICENSE) © Thevindu Guruge
