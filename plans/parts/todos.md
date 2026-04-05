# Parts project TODOs

## Anthropic plugin: spurious space TextPart from tool call workaround

When the Anthropic plugin detects tool calls in a response, it yields an extra `" "` (space character) after the tool call events. This is a workaround for a text-joining bug where the last word before a tool call and the first word of the next response would be concatenated without a space (the "can have dragons.Now that I" bug).

In `llm_anthropic.py`, sync `execute()`:
```python
if self.add_tool_usage(response, last_message):
    # Avoid "can have dragons.Now that I " bug
    yield StreamEvent(type="text", chunk=" ", part_index=part_index + 1)
```

The problem is that this space now gets persisted as a real `TextPart(role="assistant", text=" ")` in the parts table (seen as record 42 in the example chain). It's a meaningless artifact — it's not model output, it's a display hack.

### Options to fix

1. **Fix the root cause in Response/ChainResponse text joining.** The bug is presumably in how `ChainResponse.__iter__` concatenates text from consecutive responses — it `yield from`s each response with no separator. If we added a space between response boundaries in the chain, the plugin workaround could be removed entirely. Need to verify this doesn't break other plugins that don't have the bug.

2. **Filter in `_log_parts_to_db`.** Skip output TextParts that are just whitespace. Simple but lossy — what if a model legitimately outputs just a space?

3. **Mark it as metadata, not content.** The plugin could yield a different event type (e.g. `StreamEvent(type="separator")`) that the display layer handles but the parts table ignores. Cleaner but more machinery.

4. **Remove the workaround and fix in the CLI display layer.** Instead of the plugin injecting a space, have the CLI's `display_stream_events()` add a space when transitioning between chain responses. This moves the display concern out of the model plugin.

Option 4 seems cleanest — the plugin shouldn't be responsible for display formatting. The space workaround predates the parts/StreamEvent infrastructure and was the only mechanism available at the time. Now that we have structured events, the display layer can handle inter-response spacing.
