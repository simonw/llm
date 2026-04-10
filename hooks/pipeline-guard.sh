#!/usr/bin/env bash
# pipeline-guard.sh — Prevents the agent from stopping while a do-work pipeline is active.
#
# Install as a Stop hook in .claude/settings.json:
#
#   {
#     "hooks": {
#       "Stop": [
#         {
#           "hooks": [
#             {
#               "type": "command",
#               "command": "bash hooks/pipeline-guard.sh"
#             }
#           ]
#         }
#       ]
#     }
#   }
#
# Exit codes:
#   0 — Allow stop (no active pipeline or no pending steps)
#   2 — Block stop (active pipeline with pending steps)

set -euo pipefail

INPUT=$(cat)

# Never loop on hook-driven continuations
if echo "$INPUT" | grep -q '"stop_hook_active"' 2>/dev/null; then
  exit 0
fi

PIPELINE_FILE="${CLAUDE_PROJECT_DIR:-.}/do-work/pipeline.json"

if [ ! -f "$PIPELINE_FILE" ]; then
  exit 0
fi

# Parse state — prefer jq, fall back to grep
if command -v jq &>/dev/null; then
  ACTIVE=$(jq -r '.active // false' "$PIPELINE_FILE" 2>/dev/null)
  PENDING=$(jq '[.steps[] | select(.status == "pending" or .status == "in-progress")] | length' "$PIPELINE_FILE" 2>/dev/null)
  NEXT=$(jq -r '[.steps[] | select(.status == "pending" or .status == "in-progress")][0].name // "unknown"' "$PIPELINE_FILE" 2>/dev/null)
else
  ACTIVE=$(grep -o '"active"[[:space:]]*:[[:space:]]*true' "$PIPELINE_FILE" | head -1 || true)
  PENDING=$(grep -c '"status"[[:space:]]*:[[:space:]]*"pending"\|"status"[[:space:]]*:[[:space:]]*"in-progress"' "$PIPELINE_FILE" 2>/dev/null || echo "0")
  NEXT="(check do-work/pipeline.json)"
  # Normalize ACTIVE for the check below
  [ -n "$ACTIVE" ] && ACTIVE="true" || ACTIVE="false"
fi

if [ "$ACTIVE" = "true" ] && [ "$PENDING" -gt 0 ] 2>/dev/null; then
  echo "{\"decision\": \"block\", \"reason\": \"Pipeline active with $PENDING steps remaining. Next: $NEXT. Continue the pipeline.\"}"
  exit 2
fi

exit 0
