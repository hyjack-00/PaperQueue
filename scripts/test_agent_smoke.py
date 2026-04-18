"""Smoke test for agent-driven pipeline stages.

Tests that claude-glm returns valid JSON for each agent method:
  - routing (second title + notebook selection)
  - metadata extraction (structured property from NLM answer)
  - notes preflight (fourth title + slug + topic folder)
  - figure placement (section classification)

Usage:
    python scripts/test_agent_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_queue.config import settings
from paper_queue.prompt_loader import PromptLoader
import shlex
import re
import subprocess


def _call_agent(prompt: str, timeout: float = 60.0) -> dict | None:
    command_parts = shlex.split(settings.claude_glm_command)
    env = dict(os.environ)
    while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
        key, value = command_parts.pop(0).split("=", 1)
        env[key] = value
    result = subprocess.run(
        [*command_parts, "-p", "--output-format", "text", prompt],
        env=env,
        capture_output=True,
        text=True,
        cwd=settings.base_dir,
        timeout=timeout,
    )
    if result.returncode != 0:
        print(f"  Agent returned non-zero exit: {result.stderr[:200]}")
        return None
    output = result.stdout.strip()
    json_match = re.search(r"\{[^{}]*\}", output, re.S)
    if not json_match:
        print(f"  No JSON found in output: {output[:200]}")
        return None
    try:
        return json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return None


def _call_agent_list(prompt: str, timeout: float = 60.0) -> list | None:
    command_parts = shlex.split(settings.claude_glm_command)
    env = dict(os.environ)
    while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
        key, value = command_parts.pop(0).split("=", 1)
        env[key] = value
    result = subprocess.run(
        [*command_parts, "-p", "--output-format", "text", prompt],
        env=env,
        capture_output=True,
        text=True,
        cwd=settings.base_dir,
        timeout=timeout,
    )
    if result.returncode != 0:
        print(f"  Agent returned non-zero exit: {result.stderr[:200]}")
        return None
    output = result.stdout.strip()
    json_match = re.search(r"\[.*?\]", output, re.S)
    if not json_match:
        print(f"  No JSON array found in output: {output[:200]}")
        return None
    try:
        return json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return None


def test_routing():
    print("\n=== Test 1: Routing ===")
    loader = PromptLoader(settings.prompt_dir)
    prompt = loader.load(
        settings.routing_prompt_file,
        notebook_list="- ID: nb-001, Title: System Performance\n- ID: nb-002, Title: Agent Harness Evaluation\n- ID: nb-003, Title: Kernels Engineering",
        topic_list="- Kernels Engineering\n- System Performance\n- Agent Harness Evaluation\n- Ops4LLM\n- Automated Tuning\n- LLM Memory, Context, and Retrieval",
        paper_description="FlashAttention-3: Fast and Accurate Attention with Asynchronous and Low-precision GEMM on Hopper GPUs",
    )
    result = _call_agent(prompt)
    if result is None:
        print("  FAIL: No result")
        return False
    required = ["second_title", "abstract_summary", "action", "notebook_id", "topic"]
    missing = [k for k in required if k not in result]
    if missing:
        print(f"  FAIL: Missing keys: {missing}")
        return False
    if result["action"] not in ("reuse", "create"):
        print(f"  FAIL: Invalid action: {result['action']}")
        return False
    if not result["second_title"]:
        print("  FAIL: Empty second_title")
        return False
    print(f"  PASS: action={result['action']}, title={result['second_title'][:60]}")
    print(f"  abstract: {result.get('abstract_summary', '')[:80]}")
    return True


def test_metadata_extraction():
    print("\n=== Test 2: Metadata Agent ===")
    loader = PromptLoader(settings.prompt_dir)
    nlm_answer = """Full paper title: FlashAttention-3: Fast and Accurate Attention with Asynchronous and Low-precision GEMM on Hopper GPUs
Conference or journal name: arXiv
Publication year: 2024
Author list: Jay Shah, Ganesh Bikshandi, Ying Zhang, Tri Dao, Chris Ré
Author affiliations: Stanford University, Princeton University
Original paper URL: https://arxiv.org/abs/2407.08708
GitHub repository link: https://github.com/Dao-AILab/flash-attention"""
    prompt = loader.load(
        settings.metadata_agent_prompt_file,
        nlm_answer=nlm_answer,
    )
    result = _call_agent(prompt)
    if result is None:
        print("  FAIL: No result")
        return False
    required = ["third_title", "authors", "institution", "venue", "year"]
    missing = [k for k in required if k not in result]
    if missing:
        print(f"  FAIL: Missing keys: {missing}")
        return False
    if "FlashAttention" not in result["third_title"]:
        print(f"  FAIL: Title mismatch: {result['third_title']}")
        return False
    print(f"  PASS: title={result['third_title'][:60]}")
    print(f"  authors={result['authors'][:60]}, institution={result['institution']}")
    return True


def test_notes_preflight():
    print("\n=== Test 3: Notes Preflight ===")
    loader = PromptLoader(settings.prompt_dir)
    prompt = loader.load(
        settings.notes_preflight_prompt_file,
        paper_title="FlashAttention-3: Fast and Accurate Attention with Asynchronous and Low-precision GEMM on Hopper GPUs",
        venue="arXiv",
        year="2024",
        institution="Stanford University",
        authors="Jay Shah, Ganesh Bikshandi, Ying Zhang, Tri Dao, Chris Ré",
        notes_head="本文介绍了 FlashAttention-3，一种利用 Hopper GPU 异步执行和低精度矩阵乘法来加速注意力计算的方法。通过将注意力计算分解为异步 GEMM 和 softmax 操作，实现了比 FlashAttention-2 高 1.5-2.0 倍的吞吐量。",
        topic_list="- Kernels Engineering\n- System Performance\n- Agent Harness Evaluation\n- Ops4LLM\n- Automated Tuning\n- LLM Memory, Context, and Retrieval",
    )
    result = _call_agent(prompt)
    if result is None:
        print("  FAIL: No result")
        return False
    required = ["fourth_title", "title_slug", "topic_folder"]
    missing = [k for k in required if k not in result]
    if missing:
        print(f"  FAIL: Missing keys: {missing}")
        return False
    if not result["title_slug"]:
        print("  FAIL: Empty title_slug")
        return False
    print(f"  PASS: title={result['fourth_title'][:60]}")
    print(f"  slug={result['title_slug']}, topic={result['topic_folder']}")
    return True


def test_figure_placement():
    print("\n=== Test 4: Figure Placement ===")
    loader = PromptLoader(settings.prompt_dir)
    figure_info = """1. 文件名: figure-01.png | caption: Overview of the FlashAttention-3 pipeline showing asynchronous GEMM and softmax stages | 原文章节: 3 Method
2. 文件名: figure-02.png | caption: Benchmark results comparing FlashAttention-3 vs FlashAttention-2 on H100 GPU | 原文章节: 5 Experiments
3. 文件名: figure-03.png | caption: Ablation study on low-precision TF32 vs BF16 attention | 原文章节: 5.3 Ablation"""
    prompt = loader.load(
        settings.figure_placement_prompt_file,
        figure_info=figure_info,
    )
    result = _call_agent_list(prompt)
    if result is None:
        print("  FAIL: No result")
        return False
    if not isinstance(result, list) or len(result) < 3:
        print(f"  FAIL: Expected 3 items, got {len(result) if isinstance(result, list) else 'non-list'}")
        return False
    for i, item in enumerate(result):
        target = item.get("target_section", "")
        if target not in ("background", "method", "experiment", "results", "conclusion"):
            print(f"  FAIL: Invalid target_section for figure {i+1}: {target}")
            return False
    sections = [item["target_section"] for item in result]
    print(f"  PASS: {len(result)} figures classified: {sections}")
    for item in result:
        print(f"  - {item.get('figure_id', '?')} → {item['target_section']} ({item.get('reason', '')[:40]})")
    return True


def main():
    print("Agent Smoke Test")
    print(f"Backend: {settings.agent_backend}")
    print(f"Command: {settings.claude_glm_command}")
    print(f"Prompt dir: {settings.prompt_dir}")

    results = {}
    tests = [
        ("routing", test_routing),
        ("metadata", test_metadata_extraction),
        ("preflight", test_notes_preflight),
        ("figures", test_figure_placement),
    ]

    for name, test_fn in tests:
        t0 = time.time()
        try:
            ok = test_fn()
        except Exception:
            ok = False
            traceback.print_exc()
        elapsed = time.time() - t0
        results[name] = ok
        print(f"  ({elapsed:.1f}s)")

    print("\n=== Summary ===")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"\n{passed}/{total} passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
