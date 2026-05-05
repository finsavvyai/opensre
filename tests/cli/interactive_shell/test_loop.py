"""Tests for the interactive shell loop helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.input import DummyInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.output import DummyOutput

from app.cli.interactive_shell import loop


def test_build_prompt_session_uses_persistent_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.constants as const_module

    monkeypatch.setattr(const_module, "OPENSRE_HOME_DIR", tmp_path)

    with create_app_session(input=DummyInput(), output=DummyOutput()):
        prompt = loop._build_prompt_session()

    assert isinstance(prompt.history, FileHistory)
    assert prompt.history.filename == str(tmp_path / "interactive_history")
    assert tmp_path.exists()
    assert isinstance(prompt.completer, loop.SlashCommandCompleter)
    assert prompt.app.key_bindings is not None


def test_slash_completion_menu_stays_anchored_at_input_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.constants as const_module

    monkeypatch.setattr(const_module, "OPENSRE_HOME_DIR", tmp_path)

    with create_app_session(input=DummyInput(), output=DummyOutput()):
        prompt = loop._build_prompt_session()

    controls = {
        id(control): control
        for control in prompt.layout.find_all_controls()
        if isinstance(control, BufferControl) and control.buffer is prompt.default_buffer
    }

    assert len(controls) == 1
    control = next(iter(controls.values()))
    assert control.menu_position is not None

    buffer = Buffer()
    buffer.text = "/li"
    buffer.cursor_position = len(buffer.text)
    assert loop._slash_completion_menu_position(buffer) == 0


def test_build_prompt_session_falls_back_to_memory_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.constants as const_module

    blocked_home = tmp_path / "not-a-directory"
    blocked_home.write_text("", encoding="utf-8")
    monkeypatch.setattr(const_module, "OPENSRE_HOME_DIR", blocked_home)

    with create_app_session(input=DummyInput(), output=DummyOutput()):
        prompt = loop._build_prompt_session()

    assert isinstance(prompt.history, InMemoryHistory)


def test_slash_completer_previews_all_commands() -> None:
    completions = list(
        loop._build_slash_completer().get_completions(
            Document("/"),
            CompleteEvent(text_inserted=True),
        )
    )
    names = [completion.text for completion in completions]

    assert "/help" in names
    assert "/list" in names
    assert "/model" in names
    assert all(name.startswith("/") for name in names)


def test_slash_completer_filters_by_prefix() -> None:
    completions = list(
        loop._build_slash_completer().get_completions(
            Document("/li"),
            CompleteEvent(text_inserted=True),
        )
    )

    assert [completion.text for completion in completions] == ["/list"]


def test_slash_completer_keeps_exact_match_visible_and_highlighted() -> None:
    completions = list(
        loop._build_slash_completer().get_completions(
            Document("/list"),
            CompleteEvent(text_inserted=True),
        )
    )

    assert len(completions) == 1
    completion = completions[0]
    assert completion.text == "/list "
    assert completion.start_position == -len("/list")
    assert completion.display_text == "/list"
    assert completion.style == loop._EXACT_SLASH_COMMAND_STYLE
    assert completion.selected_style == loop._EXACT_SLASH_COMMAND_STYLE


def test_slash_completer_ignores_subcommand_text() -> None:
    completions = list(
        loop._build_slash_completer().get_completions(
            Document("/list "),
            CompleteEvent(text_inserted=True),
        )
    )

    assert completions == []


def test_completion_menu_supports_up_down_navigation() -> None:
    key_bindings = loop._build_prompt_key_bindings()
    keys = {binding.keys for binding in key_bindings.bindings}

    assert (Keys.Down,) in keys
    assert (Keys.Up,) in keys
    assert (Keys.Backspace,) in keys


def test_backspace_reopens_slash_completion_after_valid_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = Buffer(completer=loop._build_slash_completer())
    buffer.text = "/list"
    buffer.cursor_position = len(buffer.text)
    completion_events: list[CompleteEvent] = []

    def _start_completion(*, complete_event: CompleteEvent | None = None) -> None:
        if complete_event is not None:
            completion_events.append(complete_event)

    monkeypatch.setattr(buffer, "start_completion", _start_completion)

    loop._delete_before_cursor_and_reopen_slash_completions(buffer)

    assert buffer.text == "/lis"
    assert completion_events


def test_completion_menu_current_item_uses_subtle_highlight() -> None:
    style = loop._build_prompt_style()
    menu_attrs = style.get_attrs_for_style_str("class:completion-menu")
    attrs = style.get_attrs_for_style_str("class:completion-menu.completion.current")

    assert menu_attrs.bgcolor == "default"
    assert menu_attrs.reverse is False
    assert attrs.color == "ff7a45"
    assert attrs.bgcolor == "default"
    assert attrs.reverse is False
    assert attrs.bold is False
