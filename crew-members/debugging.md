# The Detective — Debugging Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent when debugging — during remediation attempts (Step 7 → Step 6 loop) or when the test failure loop (Step 6.5) exceeds 1 attempt. It provides a structured methodology to prevent thrashing. -->

## Core Principle: Diagnose Before You Patch

Never change code to "see if this fixes it." Every fix attempt must be preceded by a hypothesis about what's wrong and a prediction about what you'll observe if the hypothesis is correct.

## The Scientific Method for Debugging

### 1. Observe
Read the error message, stack trace, test output, or failure description. Write down exactly what happened — not what you think happened. Quote the actual output.

### 2. Hypothesize
Form a specific, falsifiable hypothesis: "The error occurs because X returns null when Y is empty." Not vague: "something is wrong with the data flow."

### 3. Predict
Before testing, predict what you'll see: "If my hypothesis is correct, adding a log before line 42 will show `value: null`." If you can't predict, your hypothesis is too vague.

### 4. Test
Run the smallest possible test of your prediction. Read the output. Does it match your prediction?

### 5. Conclude
- **Prediction matched:** Hypothesis confirmed. Now fix the root cause — not the symptom.
- **Prediction didn't match:** Hypothesis was wrong. Return to step 1 with new information. Do NOT patch anyway.

## Tool Selection by Failure Class

Pick the right diagnostic tool for the problem type — using the wrong tool wastes cycles:

| Failure Class | Recommended Tools | Why |
|---------------|------------------|-----|
| **Wrong output** | Debugger breakpoints, log assertions at boundaries | Trace data transformation step by step |
| **Performance** | Profiler (CPU/memory), flame graphs, query analyzers | Identify hotspots with actual timing data |
| **Memory leaks** | Heap snapshots, allocation tracking, GC logs | Compare snapshots over time to find growing objects |
| **Concurrency** | Thread sanitizers, race detectors, deterministic schedulers | Heisenbugs vanish under observation — use tooling that doesn't change timing |
| **Crashes** | Core dumps, stack traces, signal handlers | Post-mortem analysis preserves state at failure point |
| **Flaky tests** | Seed logging, retry with verbose output, test isolation checks | Reproduce the exact conditions — randomness and ordering are usually the cause |

### Heisenbugs

If the bug disappears when you add logging, changes behavior under a debugger, or only fails in CI: suspect a **timing-dependent bug**. Signs:
- Adding `console.log` or `print` makes it go away (I/O changes timing)
- Works in debug mode but fails in release/production (optimization changes execution order)
- Fails intermittently with no code changes (thread scheduling, GC timing, network latency)

**Response:** Don't add more logging. Use deterministic tools: thread sanitizers, recorded execution replay, or stress-test loops with fixed seeds.

## Confidence Levels

Label your diagnostic claims so the orchestrator (and future readers) know how certain you are:

- **Confirmed**: Hypothesis tested and prediction matched. Root cause identified.
- **High confidence**: Strong evidence points to this cause, but not yet fully verified.
- **Investigating**: Working theory based on initial observations. Needs more data.
Use these labels in REQ updates and escalation reports.

## Investigation Techniques

Use the technique that best fits the failure mode:

### Binary Search
Narrow the failure to the smallest possible scope. If 10 files changed and tests fail, which single file causes the failure? Revert half, test. Narrow further.

### Minimal Reproduction
Strip the failing case to its bare minimum. Remove everything that isn't necessary to trigger the bug. The simpler the reproduction, the clearer the root cause.

### Working Backwards
Start from the error and trace backwards through the call chain. At each step, verify the data is what you expect. The first point where reality diverges from expectation is near the root cause.

### Differential Debugging
Compare the working state to the broken state. What changed? `git diff` between the last passing commit and the current state. Focus on the delta, not the whole codebase.

### Follow the Indirection
When the error is "file not found" or "undefined is not a function," trace the full path: Where is the value defined? Where is it imported? Where is it passed? Where does it arrive? Indirection (aliases, re-exports, dynamic imports) hides bugs.

## Cognitive Bias Guards

| Bias | Symptom | Countermeasure |
|------|---------|----------------|
| **Confirmation** | Ignoring evidence that contradicts your theory | Actively seek disconfirming evidence. Ask: "What would I expect to see if my hypothesis is WRONG?" |
| **Anchoring** | Fixating on the first theory despite new information | After 2 failed attempts on the same theory, explicitly discard it and start fresh |
| **Availability** | Assuming the cause is something you recently encountered | Check whether this failure mode is actually related to recent changes, or if it's a different issue entirely |
| **Sunk cost** | Continuing a failing approach because you've invested time | If an approach has failed twice, abandon it. The time spent is gone regardless |

## When to Escalate

- After **2 failed fix attempts** on the same hypothesis: discard the hypothesis, form a new one
- After **3 total fix attempts** across different hypotheses: the issue may be deeper than expected. Document what you've tried and what you've learned, then report to the orchestrator as a failure with the appropriate `error_type` (classify using the failure table in work.md Step 8: `intent` for ambiguous requirements, `spec` for wrong approach, `code` for implementation bugs, `environment` for external issues) and detailed context
- If the failure is in code you didn't write and don't fully understand: document the symptom and escalate rather than guessing

## Knowledge Capture

When a non-obvious bug is resolved, capture the pattern for future sessions:

1. In the REQ's `## Lessons Learned` section, document: **symptom** (what you saw), **root cause** (what was actually wrong), **fix** (what you changed), and **how you found it** (which investigation technique worked).
2. If the bug is in an area covered by a prime file, append a debugging entry to that prime file's `## Lessons` section:
   ```
   - [REQ-NNN: Symptom → root cause → fix](relative-path-to-req#lessons-learned)
   ```

This creates a searchable knowledge base. Future builders working in the same area will read these lessons before implementing (per Step 6 instructions) and avoid repeating the same investigation.

## Anti-Patterns

- **Shotgun debugging:** Changing multiple things at once. You won't know which change fixed it — or if you introduced new bugs.
- **Print-and-pray:** Adding `console.log` everywhere without a hypothesis about what you're looking for.
- **Blame the framework:** Assuming the bug is in a library before ruling out your own code. Your code is almost always the problem.
- **Rubber-stamping:** Marking a test as passing by weakening the assertion instead of fixing the code.
- **Time-pressure patching:** Applying a workaround under pressure without understanding the root cause. The workaround becomes permanent technical debt.
