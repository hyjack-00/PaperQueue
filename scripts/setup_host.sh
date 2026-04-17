#!/usr/bin/env bash
set -euo pipefail

CLAUDE_GLM_DIR="${CLAUDE_GLM_DIR:-/home/agent-user/.claude-glm}"
SKILL_SOURCE="${SKILL_SOURCE:-/workspace/paper_reading/notebooklm-paper-reader}"
SKILL_TARGET="$CLAUDE_GLM_DIR/skills/notebooklm-paper-reader"

mkdir -p "$CLAUDE_GLM_DIR/skills"
ln -sfn "$SKILL_SOURCE" "$SKILL_TARGET"

echo "Host setup complete."
echo "Skill link: $SKILL_TARGET"
