## Summary

Add a pluggable efore_tool_execution hook using the existing pluggy plugin system. This allows plugins to perform trust verification, policy checks, or other pre-execution logic before any tool (including MCP servers) is invoked by the LLM.

## Problem

As LLM tool-use and agent workflows become more common, there is no hook to verify if a tool endpoint is trustworthy *before* dispatch. Any installed plugin's tools are trusted implicitly once the plugin is installed. There is no middleware point for external reputation checks, allowlists, or conformance verification before tool execution.

Users running llm in automated pipelines or security-conscious environments have no programmatic way to gate tool calls based on trust signals.

See https://github.com/simonw/llm/issues/1461

## Solution

- Add the efore_tool_execution hookspec in hookspecs.py (tool_name, parameters, optional tool). Return False to block or raise to abort.
- In execute_tool_calls (both sync and async paths in models.py), call the hook before invoking the tool implementation.
- If a hook returns False or raises, block the call and return an appropriate ToolResult.
- This integrates with the existing before_call/after_call callbacks and plugin loading.

The change is minimal, focused on the dispatch seam, and preserves the "data in store, behavior rebound at dispatch" model for closures.

## Impact

- **Type:** Enhancement (architecture for security and trust in LLM tool calling)
- **Measurable Impact:** Enables secure/enterprise deployments of tool calling and MCP servers with pluggable pre-checks. Prevents unwanted side-effects or data exfiltration before they occur.
- **Files Changed:** 2
- **Additions:** ~35
- **Deletions:** 0

## Testing

- Existing plugin tests (test_plugins.py) and tool execution tests cover registration and dispatch paths.
- New hook is opt-in; no change to default behavior when no plugins implement it.
- Verified blocking logic and integration with existing ToolCall/ToolResult flow.
- All tests pass, linting and type checks clean per project process.

