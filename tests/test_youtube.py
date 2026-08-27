"""Tests for yt2ascii.youtube (no network access)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from yt2ascii.errors import DownloadError, MetadataError, URLValidationError, VideoUnavailableError
from yt2ascii.youtube import (
    RawMetadata,
    download_audio,
    download_video,
    extract_metadata,
    validate_url,
)

VALID_ID = "dQw4w9WgXcQ"


class FakeYDL:
    def __init__(
        self,
        info: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        writes_file: Path | None = None,
    ) -> None:
        self._info = info
        self._error = error
        self._writes_file = writes_file
        self.requested_url: str | None = None

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        self.requested_url = url
        if self._error is not None:
            raise self._error
        if download and self._writes_file is not None:
            self._writes_file.write_bytes(b"\x00\x00fake video\x00\x00")
        assert self._info is not None
        return self._info

    def prepare_filename(self, info: dict[str, Any]) -> str:
        if self._writes_file is not None:
            return str(self._writes_file)
        return f"{info.get('id', 'video')}.mp4"


def _factory(ydl: FakeYDL):
    @contextmanager
    def make(_opts: dict[str, Any]):
        yield ydl

    return make


class TestValidateUrl:
    @pytest.mark.parametrize(
        "url",
        [
            f"https://www.youtube.com/watch?v={VALID_ID}",
            f"http://youtube.com/watch?v={VALID_ID}&t=30s",
            f"https://youtu.be/{VALID_ID}",
            f"https://youtu.be/{VALID_ID}?si=abcd",
            f"https://www.youtube.com/shorts/{VALID_ID}",
            f"https://m.youtube.com/watch?v={VALID_ID}",
            f"https://www.youtube.com/embed/{VALID_ID}",
            f"https://www.youtube.com/watch?v={VALID_ID}&list=RD{VALID_ID}&index=2&pp=8AUB",
            # scheme-less pastes
            f"youtube.com/watch?v={VALID_ID}",
            f"www.youtube.com/watch?v={VALID_ID}",
            f"youtu.be/{VALID_ID}?si=HCojqkv1SBOvO89Q",
            # bare video id
            VALID_ID,
        ],
    )
    def test_accepts_and_canonicalises(self, url: str) -> None:
        assert validate_url(url) == f"https://www.youtube.com/watch?v={VALID_ID}"

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "not a url",
            "ftp://youtube.com/watch?v=" + VALID_ID,
            "https://vimeo.com/12345",
            "https://www.youtube.com/watch?v=tooshort",
            "https://www.youtube.com/watch",
            "https://example.com/watch?v=" + VALID_ID,
        ],
    )
    def test_rejects(self, url: str) -> None:
        with pytest.raises(URLValidationError):
            validate_url(url)


class TestExtractMetadata:
    def _info(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "id": VALID_ID,
            "title": "Example Video",
            "duration": 102,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "webpage_url": f"https://www.youtube.com/watch?v={VALID_ID}",
        }
        base.update(overrides)
        return base

    def test_returns_metadata(self) -> None:
        ydl = FakeYDL(self._info())
        meta = extract_metadata(
            f"https://youtu.be/{VALID_ID}", ydl_factory=_factory(ydl)
        )
        assert isinstance(meta, RawMetadata)
        assert meta.title == "Example Video"
        assert meta.duration == 102.0
        assert (meta.width, meta.height, meta.fps) == (1920, 1080, 30.0)
        assert ydl.requested_url == f"https://www.youtube.com/watch?v={VALID_ID}"

    def test_dimensions_from_formats_fallback(self) -> None:
        info = self._info(width=None, height=None, fps=None)
        info["formats"] = [{"width": 640, "height": 360, "fps": 24}]
        meta = extract_metadata(
            f"https://youtu.be/{VALID_ID}", ydl_factory=_factory(FakeYDL(info))
        )
        assert (meta.width, meta.height, meta.fps) == (640, 360, 24.0)

    def test_missing_duration_is_metadata_error(self) -> None:
        with pytest.raises(MetadataError):
            extract_metadata(
                f"https://youtu.be/{VALID_ID}",
                ydl_factory=_factory(FakeYDL(self._info(duration=None))),
            )

    @pytest.mark.parametrize(
        ("message", "exc"),
        [
            ("ERROR: Private video. Sign in if granted access", VideoUnavailableError),
            ("ERROR: Video unavailable", VideoUnavailableError),
            ("ERROR: This video has been removed by the uploader", VideoUnavailableError),
            ("Sign in to confirm your age (age restricted)", VideoUnavailableError),
            ("ERROR: not made this video available in your country", VideoUnavailableError),
            ("Sign in to confirm you're not a bot", VideoUnavailableError),
            ("ERROR: some unexpected failure", MetadataError),
            # A page-fetch/SSL failure must not be mistaken for "age" in "page".
            (
                "ERROR: Unable to download API page: [SSL: CERTIFICATE_VERIFY_FAILED]. "
                "Confirm you are on the latest version",
                MetadataError,
            ),
        ],
    )
    def test_translates_ydl_errors(self, message: str, exc: type[Exception]) -> None:
        ydl = FakeYDL(error=RuntimeError(message))
        with pytest.raises(exc) as excinfo:
            extract_metadata(
                f"https://youtu.be/{VALID_ID}", ydl_factory=_factory(ydl)
            )
        if "SSL" in message:
            assert "internet connection" in str(excinfo.value)


class TestDownloadVideo:
    def test_downloads_to_dest_dir(self, tmp_path: Path) -> None:
        target = tmp_path / f"{VALID_ID}.mp4"
        ydl = FakeYDL({"id": VALID_ID}, writes_file=target)
        path = download_video(
            f"https://youtu.be/{VALID_ID}", tmp_path, ydl_factory=_factory(ydl)
        )
        assert path == target
        assert path.exists()

    def test_falls_back_to_tagged_file(self, tmp_path: Path) -> None:
        (tmp_path / f"{VALID_ID}.audio.m4a").write_bytes(b"x" * 9)  # other stream
        big = tmp_path / f"{VALID_ID}.video.webm"
        big.write_bytes(b"x" * 5000)
        ydl = FakeYDL({"id": VALID_ID})  # prepare_filename -> non-existent .mp4
        path = download_video(
            f"https://youtu.be/{VALID_ID}", tmp_path, ydl_factory=_factory(ydl)
        )
        assert path == big

    def test_no_output_file_raises(self, tmp_path: Path) -> None:
        ydl = FakeYDL({"id": VALID_ID})
        with pytest.raises(DownloadError):
            download_video(
                f"https://youtu.be/{VALID_ID}", tmp_path, ydl_factory=_factory(ydl)
            )

    def test_download_error_is_translated(self, tmp_path: Path) -> None:
        ydl = FakeYDL(error=RuntimeError("ERROR: Private video"))
        with pytest.raises(VideoUnavailableError):
            download_video(
                f"https://youtu.be/{VALID_ID}", tmp_path, ydl_factory=_factory(ydl)
            )


class TestDownloadAudio:
    def test_downloads_audio_stream(self, tmp_path: Path) -> None:
        target = tmp_path / f"{VALID_ID}.audio.m4a"
        ydl = FakeYDL({"id": VALID_ID}, writes_file=target)
        path = download_audio(
            f"https://youtu.be/{VALID_ID}", tmp_path, ydl_factory=_factory(ydl)
        )
        assert path == target
        assert path.exists()

    def test_missing_audio_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DownloadError):
            download_audio(
                f"https://youtu.be/{VALID_ID}",
                tmp_path,
                ydl_factory=_factory(FakeYDL({"id": VALID_ID})),
            )
