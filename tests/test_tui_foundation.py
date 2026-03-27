"""Tests for tui/ foundation: messages, terminal, FakeTerminal."""

import time

import pytest

from tui.messages import Msg, MsgType, STREAM_DEFAULTS, register_msg_type, is_registered
from tui.terminal import Terminal, FakeTerminal, ERASE_LINE, CURSOR_UP_FMT, ERASE_DOWN

# ── MsgType ───────────────────────────────────────────────────────────


class TestMsgType:
    def test_core_types_exist(self):
        assert MsgType.CONTENT.value == "content"
        assert MsgType.CONTENT_FINISH.value == "content_finish"
        assert MsgType.EPHEMERAL.value == "ephemeral"
        assert MsgType.HTTP_DEBUG.value == "http_debug"
        assert MsgType.TOOL_STATUS.value == "tool_status"
        assert MsgType.SEPARATOR.value == "separator"
        assert MsgType.ERROR.value == "error"
        assert MsgType.STOP.value == "stop"

    def test_stream_defaults(self):
        assert STREAM_DEFAULTS[MsgType.CONTENT] == "stdout"
        assert STREAM_DEFAULTS[MsgType.HTTP_DEBUG] == "stderr"
        assert STREAM_DEFAULTS[MsgType.ERROR] == "stderr"
        assert STREAM_DEFAULTS[MsgType.EPHEMERAL] == "stdout"
        assert STREAM_DEFAULTS[MsgType.TOOL_STATUS] == "stderr"


# ── Msg ───────────────────────────────────────────────────────────────


class TestMsg:
    def test_defaults(self):
        msg = Msg(kind=MsgType.CONTENT)
        assert msg.kind == MsgType.CONTENT
        assert msg.text == ""
        assert msg.source == ""
        assert msg.request_id == ""
        assert msg.chunk_index == 0
        assert msg.is_final is False
        assert msg.meta == {}
        assert msg.stream is None

    def test_fields(self):
        msg = Msg(
            kind=MsgType.CONTENT,
            text="hello",
            source="openai",
            request_id="req_123",
            chunk_index=5,
            is_final=True,
            meta={"model": "gpt-4"},
            stream="stderr",
        )
        assert msg.text == "hello"
        assert msg.source == "openai"
        assert msg.request_id == "req_123"
        assert msg.chunk_index == 5
        assert msg.is_final is True
        assert msg.meta == {"model": "gpt-4"}
        assert msg.stream == "stderr"

    def test_frozen(self):
        msg = Msg(kind=MsgType.CONTENT, text="hello")
        with pytest.raises(AttributeError):
            msg.text = "world"  # type: ignore[misc]

    def test_timestamp_auto(self):
        before = time.monotonic()
        msg = Msg(kind=MsgType.CONTENT)
        after = time.monotonic()
        assert before <= msg.ts <= after

    def test_resolve_stream_default(self):
        msg = Msg(kind=MsgType.CONTENT)
        assert msg.resolve_stream() == "stdout"
        msg2 = Msg(kind=MsgType.HTTP_DEBUG)
        assert msg2.resolve_stream() == "stderr"

    def test_resolve_stream_override(self):
        msg = Msg(kind=MsgType.CONTENT, stream="stderr")
        assert msg.resolve_stream() == "stderr"

    def test_resolve_stream_plugin_type(self):
        msg = Msg(kind="plugin.custom", text="hi")
        assert msg.resolve_stream() == "stdout"


# ── Plugin type registry ──────────────────────────────────────────────


class TestPluginRegistry:
    def test_core_types_registered(self):
        assert is_registered(MsgType.CONTENT)
        assert is_registered(MsgType.STOP)

    def test_unknown_string_not_registered(self):
        assert not is_registered("unknown.type")

    def test_register_and_check(self):
        name = register_msg_type("test.custom_type")
        assert name == "test.custom_type"
        assert is_registered("test.custom_type")

    def test_register_returns_name(self):
        result = register_msg_type("test.another")
        assert result == "test.another"


# ── Terminal ──────────────────────────────────────────────────────────


class TestTerminal:
    def test_width_default(self):
        t = Terminal()
        w = t.width()
        assert isinstance(w, int)
        assert w > 0

    def test_height_default(self):
        t = Terminal()
        h = t.height()
        assert isinstance(h, int)
        assert h > 0


# ── FakeTerminal ──────────────────────────────────────────────────────


class TestFakeTerminal:
    def test_write_stdout(self):
        ft = FakeTerminal()
        ft.write("hello", "stdout")
        assert ft.stdout_text == "hello"
        assert ft.stderr_text == ""

    def test_write_stderr(self):
        ft = FakeTerminal()
        ft.write("error", "stderr")
        assert ft.stderr_text == "error"
        assert ft.stdout_text == ""

    def test_write_multiple(self):
        ft = FakeTerminal()
        ft.write("a")
        ft.write("b")
        ft.write("c")
        assert ft.stdout_text == "abc"

    def test_clear_line(self):
        ft = FakeTerminal()
        ft.clear_line()
        assert ERASE_LINE in ft.stdout_text
        assert ("clear_line", "stdout") in ft.operations

    def test_cursor_up(self):
        ft = FakeTerminal()
        ft.cursor_up(3)
        assert CURSOR_UP_FMT.format(3) in ft.stdout_text
        assert ("cursor_up", "stdout", "3") in ft.operations

    def test_cursor_up_zero(self):
        ft = FakeTerminal()
        ft.cursor_up(0)
        # Should record operation but not write escape
        assert ("cursor_up", "stdout", "0") in ft.operations

    def test_erase_down(self):
        ft = FakeTerminal()
        ft.erase_down()
        assert ERASE_DOWN in ft.stdout_text

    def test_erase_rows(self):
        ft = FakeTerminal()
        ft.erase_rows(2)
        assert ("erase_rows", "stdout", "2") in ft.operations
        # Should include cursor_up and erase_down
        assert CURSOR_UP_FMT.format(2) in ft.stdout_text
        assert ERASE_DOWN in ft.stdout_text

    def test_erase_rows_zero(self):
        ft = FakeTerminal()
        ft.erase_rows(0)
        assert ("erase_rows", "stdout", "0") in ft.operations
        # No cursor movement for 0 rows
        assert ft.stdout_text == ""

    def test_is_tty(self):
        ft = FakeTerminal()
        assert ft.is_tty is True
        assert ft.use_color is True

    def test_dimensions(self):
        ft = FakeTerminal()
        assert ft.width() == 80
        assert ft.height() == 24

    def test_reset(self):
        ft = FakeTerminal()
        ft.write("hello")
        ft.write("error", "stderr")
        ft.clear_line()
        ft.reset()
        assert ft.stdout_text == ""
        assert ft.stderr_text == ""
        assert ft.operations == []

    def test_operations_order(self):
        ft = FakeTerminal()
        ft.write("a")
        ft.clear_line()
        ft.write("b")
        ops = [op[0] for op in ft.operations]
        assert ops == ["write", "clear_line", "write", "write"]

    def test_write_line(self):
        ft = FakeTerminal()
        ft.write_line("hello")
        assert ft.stdout_text == "hello\n"
