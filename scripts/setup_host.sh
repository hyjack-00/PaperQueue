#!/usr/bin/env bash
set -euo pipefail

NEXTCLOUD_DATA_ROOT="${NEXTCLOUD_DATA_ROOT:-/workspace/nextcloud/data/data/admin/files}"
VAULT_ROOT="${VAULT_ROOT:-MAIN}"
PAPER_ROOT="$NEXTCLOUD_DATA_ROOT/$VAULT_ROOT/paper"
CLAUDE_GLM_DIR="${CLAUDE_GLM_DIR:-/home/agent-user/.claude-glm}"
SKILL_SOURCE="${SKILL_SOURCE:-/workspace/paper_reading/notebooklm-paper-reader}"
SKILL_TARGET="$CLAUDE_GLM_DIR/skills/notebooklm-paper-reader"

sudo mkdir -p "$PAPER_ROOT"
sudo chown -R www-data:www-data "$PAPER_ROOT"
sudo chmod 2777 "$PAPER_ROOT"
sudo usermod -a -G www-data agent-user

mkdir -p "$CLAUDE_GLM_DIR/skills"
ln -sfn "$SKILL_SOURCE" "$SKILL_TARGET"

echo "Host setup complete."
echo "Paper root: $PAPER_ROOT"
echo "Skill link: $SKILL_TARGET"
echo "If agent-user was newly added to www-data, restart the shell or login session before starting the queue service."
