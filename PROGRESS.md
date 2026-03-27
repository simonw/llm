---
project: "TUI Abstraction Layer Refactor"
working-dir: "/Users/gaston/Projects/ai/llm-tools/llm"
status: completed
created-at: "2026-03-26T20:39:25.716614000-0400"
updated-at: "2026-03-26T20:51:57.050220000-0400"
agents:
  - id: "claude-opus-4-6"
    role: "lead-implementer"
    first-seen: "2026-03-26T20:39:25.716614000-0400"
parent: null
related: []
trailog:
  - "2026-03-26T20:39:25.716614000-0400": "Created PROGRESS.md. Phases 1-5 tui/ package built. 668 tests pass. Remaining: wire TUI into CLI commands, delete dead code."
  - "2026-03-26T20:46:56.238109000-0400": "COMPLETED. All 9 phases done. 668 tests pass, lint clean. TUI wired into prompt() and chat(). Dead code deleted (_make_spinner, _wrap_tool_callbacks_for_spinner)."
  - "2026-03-26T20:51:57.050220000-0400": "Audited all remaining dead/legacy code and follow-up items. 13 follow-ups documented in backlog."
---

# Research Progress Log

## Completed Investigations

### [2026-03-26T20:39:25.716614000-0400] Investigation: TUI Abstraction Layer — Full Implementation

#### Context
- Goal: Replace fragmented terminal output (spinner→stdout, HTTP debug→stderr, streaming→stdout) with unified TUI layer
- Trigger: Spinner frames permanently stranded in scrollback due to stdout/stderr cursor interleaving

#### Results
- [x] Phase 1: tui/messages.py + tui/terminal.py + FakeTerminal — 29 tests
  - Certainty: **Observed** — all tests pass
- [x] Phase 2: tui/spinner.py (SpinnerState) + tui/consumer.py (Consumer thread) — 18 tests
  - Certainty: **Observed** — spinner no-stranding test passes with FakeTerminal
- [x] Phase 3: tui/renderers/http_debug.py (TUIHTTPHandler + TUISpinnerHandler) + upgrade_http_logging_to_tui() — 10 tests
  - Certainty: **Observed** — HTTP debug routes through TUI queue
- [x] Phase 4: tools/mdstream.py → tui/renderers/markdown.py + backward-compat stub
  - Certainty: **Observed** — both old and new import paths work
- [x] Phase 5: tui/capture.py (ScopedCapture) + llm/cli_output.py — 5 tests
  - Certainty: **Observed** — print() inside scoped capture routes through TUI
- [x] Phase 6: TUI wired into prompt() — replaced old Spinner + buffered_stream_end
  - Certainty: **Observed** — 668 tests pass
- [x] Phase 7: TUI wired into chat() — replaced old Spinner + buffered_stream_end
  - Certainty: **Observed** — 668 tests pass
- [x] Phase 8: Deleted _make_spinner, _wrap_tool_callbacks_for_spinner, buffered_stream_end import
  - Certainty: **Observed** — 668 tests pass, lint clean
- [x] Phase 9: Final verification — 668 tests, lint clean
  - Certainty: **Observed**

#### Files Created (10 new)
- tui/__init__.py (TUI class)
- tui/messages.py (Msg, MsgType, plugin registry)
- tui/terminal.py (Terminal, FakeTerminal)
- tui/spinner.py (SpinnerState)
- tui/consumer.py (Consumer thread)
- tui/capture.py (ScopedCapture)
- tui/renderers/__init__.py
- tui/renderers/http_debug.py (TUIHTTPHandler, TUISpinnerHandler)
- tui/renderers/markdown.py (moved from tools/mdstream.py)
- llm/cli_output.py (create_tui, wrap_tool_callbacks_for_tui)

#### Files Modified (6)
- llm/cli.py — prompt() and chat() use TUI, deleted _make_spinner + _wrap_tool_callbacks_for_spinner
- llm/utils.py — configure_http_logging(tui=), upgrade_http_logging_to_tui()
- tools/mdstream.py — backward-compat stub re-exporting from tui/renderers/markdown
- pyproject.toml — added tui + tui.renderers packages, updated mdstream entry point
- tests/test_llm.py — updated to test TUI equivalents
- tests/test_mdstream.py — updated monkeypatch path

## Ideas & Hypotheses Backlog

### Dead code still in codebase (safe to delete once TUI is sole path)

- [ ] Delete `_ColorWriter` class (llm/cli.py:4439) — prompt() and chat() still use it for mdstream rendering. Replace with TUI consumer's md_renderer path, then delete.
- [ ] Delete `_QuietStreamHandler` class (llm/utils.py:380) — still used by legacy `configure_http_logging(tui=None)` path. Once all callers pass `tui`, remove.
- [ ] Delete `SpinnerLogHandler` class (llm/utils.py:1629) — still imported by `tools/spinner.py:290` and used in `upgrade_http_logging_to_tui()` to filter out old handlers. Remove once old Spinner class is unused.
- [ ] Delete `buffered_stream_end()` function (llm/utils.py:1678) — no longer called in prompt()/chat(). Check if any other callers exist, then remove.
- [ ] Delete `_defer_stream_end` / `_pending_stream_end` class vars on HTTPColorFormatter (llm/utils.py:613-614) — only used by buffered_stream_end(). Remove together.
- [ ] Delete old `Spinner` class (tools/spinner.py:152-428) — still imported by tests/test_spinner.py. Migrate those tests to SpinnerState, then delete or stub the file.
- [ ] Delete `tools/spinner.py` entirely or replace with re-export stub like tools/mdstream.py

### Structural refactors

- [?] Full cli.py split into cli_commands.py, cli_tools.py — 4500 lines, by-concern extraction. Deferred: large, low risk-reward right now (confidence: high)
- [?] Route _ColorWriter writes through TUI consumer instead of direct stdout — consumer already has md_renderer support in _render_content(). Would fully unify all output. (confidence: med)
- [?] Move HTTPColorFormatter from llm/utils.py into tui/renderers/http_debug.py — 950 lines, mechanical move. Ported as-is per plan, physical move deferred. (confidence: high)

### TUI enhancements

- [?] Dedicated status bar region (bottom N lines) — API designed for it (ephemeral_rows tracking, erase_rows). Not implemented yet. (confidence: med)
- [?] TUI-native spinner persist mode — old Spinner had LLM_SPINNER_PERSIST env var. SpinnerState doesn't handle this yet. Consumer would need a persist message type. (confidence: med)
- [?] Non-TTY plain mode in TUI — PlainTUI subclass sketched in plan but not implemented. Currently TUI drops ephemeral and writes content directly. May need refinement. (confidence: med)

## Sources & References

- Plan file: `/Users/gaston/.claude/plans/greedy-leaping-journal.md`

## Archive

(empty)
