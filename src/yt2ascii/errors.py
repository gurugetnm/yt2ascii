"""Exception hierarchy for yt2ascii.

Every error surfaced to a normal user is a :class:`Yt2AsciiError` with a
human-readable message. The CLI catches this base class and prints the message
without a Python traceback.
"""

from __future__ import annotations


class Yt2AsciiError(Exception):
    """Base class for all expected, user-facing errors."""


class ConfigError(Yt2AsciiError):
    """Invalid combination of command-line options or configuration values."""


class URLValidationError(Yt2AsciiError):
    """The supplied string is not a URL yt2ascii knows how to handle."""


class MetadataError(Yt2AsciiError):
    """yt-dlp could not return usable metadata for the video."""


class VideoUnavailableError(Yt2AsciiError):
    """The video exists in some form but cannot be played.

    Covers private, deleted, region-locked and age-restricted videos.
    """


class DownloadError(Yt2AsciiError):
    """The video could not be downloaded or decoded."""


class DurationLimitError(Yt2AsciiError):
    """The video is longer than the configured maximum duration."""


class DependencyError(Yt2AsciiError):
    """A required external dependency (e.g. FFmpeg) is missing."""


class TerminalError(Yt2AsciiError):
    """The current terminal cannot support playback."""
