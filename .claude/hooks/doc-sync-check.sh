#!/usr/bin/env bash
# Doc-sync stop hook — blocks Claude from stopping if source files changed
# without corresponding doc updates. Zero LLM tokens, ~100ms execution.
#
# Uses stop_hook_active flag to prevent infinite retry loops.

set -euo pipefail

# Read stdin JSON for stop_hook_active flag
INPUT=$(cat)
if echo "$INPUT" | grep -q '"stop_hook_active"'; then
  exit 0  # Already retried once — allow stop
fi

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# Find modified source files (staged + unstaged)
SRC_CHANGED=$(git diff --name-only HEAD 2>/dev/null | grep -E '\.(py|js|ts|nix|html)$' || true)

if [ -z "$SRC_CHANGED" ]; then
  exit 0  # No source changes — allow stop
fi

# Find modified doc files
DOC_CHANGED=$(git diff --name-only HEAD 2>/dev/null | grep -E '(CLAUDE\.md|ARCHITECTURE\.md|CURRENT_STATE\.md|DEPLOYMENT\.md)' || true)

if [ -z "$DOC_CHANGED" ]; then
  echo "BLOCKED: Source files changed but no documentation updated."
  echo ""
  echo "Changed source files:"
  echo "$SRC_CHANGED" | sed 's/^/  - /'
  echo ""
  echo "Update the relevant CLAUDE.md or docs/ file before finishing."
  exit 1
fi

exit 0
