"""YouTube URL handling, metadata extraction, and downloading via yt-dlp.

External input (the URL) is validated before it is ever handed to yt-dlp, and
yt-dlp's own errors are translated into the :class:`~yt2ascii.errors.Yt2AsciiError`
hierarchy so the CLI can show a friendly message instead of a traceback.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlparse

from .errors import DownloadError, MetadataError, URLValidationError, VideoUnavailableError

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_PATH_ID_PREFIXES = ("/shorts/", "/embed/", "/v/", "/live/")

#: Cap the download resolution: ASCII art never needs more than ~200 columns.
DEFAULT_MAX_HEIGHT = 720


class _YoutubeDLLike(Protocol):
    def extract_info(self, url: str, download: bool = ...) -> dict[str, Any]: ...

    def prepare_filename(self, info: dict[str, Any]) -> str: ...


YdlFactory = Callable[[dict[str, Any]], AbstractContextManager[_YoutubeDLLike]]


@dataclass(frozen=True, slots=True)
class RawMetadata:
    """Video facts needed before playback, as returned by yt-dlp."""

    video_id: str
    title: str
    duration: float
    width: int
    height: int
    fps: float
    webpage_url: str


# --------------------------------------------------------------------------- #
# URL validation
# --------------------------------------------------------------------------- #
def validate_url(url: str) -> str:
    """Validate a YouTube URL and return the canonical ``watch?v=`` form.

    Raises :class:`URLValidationError` for anything that is not an
    ``http(s)`` URL on a known YouTube host carrying an 11-character video id.
    """

    if not isinstance(url, str) or not url.strip():
        raise URLValidationError("No URL was provided.")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise URLValidationError(
            f"'{url}' is not a valid http(s) URL."
        )

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _YOUTUBE_HOSTS:
        raise URLValidationError(
            f"'{host or url}' is not a recognised YouTube domain."
        )

    video_id = _extract_video_id(host, parsed.path, parsed.query)
    if video_id is None or not _VIDEO_ID_RE.fullmatch(video_id):
        raise URLValidationError(
            "Could not find a valid YouTube video id in the URL."
        )
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_video_id(host: str, path: str, query: str) -> str | None:
    if host == "youtu.be":
        return path.lstrip("/").split("/", 1)[0] or None

    if path == "/watch":
        values = parse_qs(query).get("v", [])
        return values[0] if values else None

    for prefix in _PATH_ID_PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix) :].split("/", 1)[0] or None
    return None


# --------------------------------------------------------------------------- #
# yt-dlp integration
# --------------------------------------------------------------------------- #
_BASE_YDL_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "noprogress": True,
    "retries": 3,
    "socket_timeout": 30,
}


def _default_ydl_factory(opts: dict[str, Any]) -> AbstractContextManager[_YoutubeDLLike]:
    from yt_dlp import YoutubeDL

    return cast(
        "AbstractContextManager[_YoutubeDLLike]",
        YoutubeDL({**_BASE_YDL_OPTS, **opts}),
    )


def _classify_ydl_error(message: str) -> MetadataError | VideoUnavailableError | DownloadError:
    text = message.lower()
    if "private" in text:
        return VideoUnavailableError("This video is private.")
    if "age" in text and ("confirm" in text or "restrict" in text or "sign in" in text):
        return VideoUnavailableError(
            "This video is age restricted and cannot be played without signing in."
        )
    if any(
        phrase in text
        for phrase in (
            "video unavailable",
            "no longer available",
            "has been removed",
            "been terminated",
            "does not exist",
            "deleted",
        )
    ):
        return VideoUnavailableError("This video is unavailable or has been removed.")
    if any(
        phrase in text
        for phrase in (
            "available in your country",
            "available in your location",
            "geo-restrict",
            "geo restrict",
            "geoblock",
            "not available in your region",
        )
    ):
        return VideoUnavailableError("This video is not available in your region.")
    if "sign in to confirm" in text or "bot" in text:
        return VideoUnavailableError(
            "YouTube is asking for sign-in verification for this video; it cannot be played."
        )
    return MetadataError(f"YouTube request failed: {message.strip()}")


def _run_ydl(
    url: str,
    opts: dict[str, Any],
    *,
    download: bool,
    factory: YdlFactory | None,
) -> tuple[_YoutubeDLLike, dict[str, Any]]:
    make = factory or _default_ydl_factory
    try:
        with make(opts) as ydl:
            info = ydl.extract_info(url, download=download)
            return ydl, info
    except (URLValidationError, VideoUnavailableError, MetadataError, DownloadError):
        raise
    except Exception as exc:
        raise _classify_ydl_error(str(exc)) from exc


def _pick_dimensions(info: dict[str, Any]) -> tuple[int, int, float]:
    width = _as_int(info.get("width"))
    height = _as_int(info.get("height"))
    fps = _as_float(info.get("fps"))

    candidates: Iterable[dict[str, Any]] = (
        info.get("requested_formats") or info.get("formats") or []
    )
    for fmt in candidates:
        if not width or not height:
            width = width or _as_int(fmt.get("width"))
            height = height or _as_int(fmt.get("height"))
        if not fps:
            fps = _as_float(fmt.get("fps"))
    return width, height, fps


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def extract_metadata(url: str, *, ydl_factory: YdlFactory | None = None) -> RawMetadata:
    """Fetch metadata for ``url`` without downloading the media."""

    canonical = validate_url(url)
    _, info = _run_ydl(
        canonical, {"skip_download": True}, download=False, factory=ydl_factory
    )
    if info is None:
        raise MetadataError("YouTube returned no information for this video.")

    duration = info.get("duration")
    if duration is None:
        raise MetadataError(
            "This video has no fixed duration (it may be a live stream), which is "
            "not supported."
        )

    width, height, fps = _pick_dimensions(info)
    return RawMetadata(
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or "Untitled"),
        duration=float(duration),
        width=width,
        height=height,
        fps=fps,
        webpage_url=str(info.get("webpage_url") or canonical),
    )


def download_video(
    url: str,
    dest_dir: Path,
    *,
    max_height: int = DEFAULT_MAX_HEIGHT,
    ydl_factory: YdlFactory | None = None,
) -> Path:
    """Download the (video-only) stream for ``url`` into ``dest_dir``.

    A video-only progressive format is preferred so that playback does not
    depend on a system FFmpeg for muxing.
    """

    canonical = validate_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts: dict[str, Any] = {
        "skip_download": False,
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]/"
            f"best[height<={max_height}][ext=mp4]/"
            f"bestvideo[height<={max_height}]/best[height<={max_height}]/best"
        ),
    }
    ydl, info = _run_ydl(canonical, opts, download=True, factory=ydl_factory)
    if info is None:
        raise DownloadError("The video could not be downloaded.")

    path = Path(ydl.prepare_filename(info))
    if path.exists():
        return path

    produced = sorted(
        (p for p in dest_dir.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not produced:
        raise DownloadError("The video download did not produce a file.")
    return produced[0]
