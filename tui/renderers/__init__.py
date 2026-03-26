"""Renderer protocol and registry for the TUI layer.

Renderers transform ``Msg`` objects into terminal output.  The consumer
thread calls renderers from a single thread, so they do not need to be
thread-safe.
"""
