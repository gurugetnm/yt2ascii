"""Tests for yt2ascii.terminal."""

from __future__ import annotations

import io
import os

import pytest

from yt2ascii import terminal
from yt2ascii.config import MAX_WIDTH, MIN_WIDTH
from yt2ascii.terminal import (
    CURSOR_HOME,
    HIDE_CURSOR,
    SHOW_CURSOR,
    TerminalController,
    TerminalSize,
    get_terminal_size,
    move_cursor,
    resolve_width,
)


class _FakeStdin(io.StringIO):
    def __init__(self, tty: bool = False) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_move_cursor_format() -> None:
    assert move_cursor() == "\033[1;1H"
    assert move_cursor(5, 12) == "\033[5;12H"


def test_get_terminal_size_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "")
    monkeypatch.setenv("LINES", "")
    monkeypatch.setattr(
        terminal.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size(fallback),
    )
    size = get_terminal_size(fallback=(100, 40))
    assert size == TerminalSize(columns=100, rows=40)


class TestResolveWidth:
    def test_auto_width_subtracts_margin(self) -> None:
        result = resolve_width(None, terminal_columns=120, margin=2)
        assert result.width == 118
        assert result.clamped_to_terminal is False

    def test_requested_within_budget(self) -> None:
        result = resolve_width(80, terminal_columns=120)
        assert result.width == 80
        assert result.clamped_to_terminal is False

    def test_requested_wider_than_terminal_is_clamped(self) -> None:
        result = resolve_width(200, terminal_columns=100, margin=2)
        assert result.width == 98
        assert result.clamped_to_terminal is True

    def test_hard_max_width(self) -> None:
        result = resolve_width(9999, terminal_columns=100_000, margin=0)
        assert result.width == MAX_WIDTH

    def test_min_width_floor(self) -> None:
        result = resolve_width(1, terminal_columns=5, margin=0)
        assert result.width == MIN_WIDTH


class TestTerminalController:
    def test_enter_hides_cursor_exit_restores(self) -> None:
        out = io.StringIO()
        controller = TerminalController(out=out, stdin=_FakeStdin(tty=False))
        with controller as ctl:
            assert ctl.interactive is False
            assert out.getvalue().startswith(HIDE_CURSOR)
        assert SHOW_CURSOR in out.getvalue()

    def test_read_key_returns_none_without_tty(self) -> None:
        controller = TerminalController(out=io.StringIO(), stdin=_FakeStdin(tty=False))
        with controller as ctl:
            assert ctl.read_key() is None

    def test_draw_moves_home_and_erases_lines(self) -> None:
        out = io.StringIO()
        controller = TerminalController(out=out, stdin=_FakeStdin(tty=False))
        with controller:
            out.seek(0)
            out.truncate(0)
            controller.draw("ab\ncd")
        written = out.getvalue()
        assert written.startswith(CURSOR_HOME)
        assert "ab\033[K\ncd\033[K" in written

    def test_draw_with_status_line(self) -> None:
        out = io.StringIO()
        controller = TerminalController(out=out, stdin=_FakeStdin(tty=False))
        with controller:
            out.seek(0)
            out.truncate(0)
            controller.draw("frame", status="FPS: 15", rows=3)
        written = out.getvalue()
        assert "FPS: 15" in written
        assert move_cursor(5, 1) in written

    def test_exit_restores_even_after_exception(self) -> None:
        out = io.StringIO()
        controller = TerminalController(out=out, stdin=_FakeStdin(tty=False))
        with pytest.raises(RuntimeError), controller:
            raise RuntimeError("boom")
        assert SHOW_CURSOR in out.getvalue()
