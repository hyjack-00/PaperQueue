#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/paper_reading"
cd "$ROOT"

echo "Local benchmark scores:"
python3 "$ROOT/scripts/evaluate_swiftscholar_benchmark.py"

cat <<'EOF'

Sub-agent review checklist:
- Audit structure drift against SwiftScholar-like layout.
- Audit missing content items for each benchmark paper.
- Audit whether figures appear in the correct semantic section.
- Report per-paper gaps and average release-gate readiness.

Use this prompt when delegating:
Review the generated benchmark notes under /workspace/obsidian_sync/paper and score them against /workspace/paper_reading/benchmarks/swiftscholar_benchmark.json.
Return only: per-paper gaps, average scores, and the next prompt adjustment recommendation.
EOF
