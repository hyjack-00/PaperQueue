from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from paper_queue.config import settings
from paper_queue.evaluation import build_note_metrics, find_note, run_agent_prompt, split_text_batches
from paper_queue.prompt_loader import PromptLoader

BENCHMARKS = json.loads((BASE_DIR / "benchmarks" / "swiftscholar_benchmark.json").read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


STOPWORDS = {
    "the", "and", "that", "with", "from", "this", "these", "those", "into", "over",
    "for", "are", "was", "were", "have", "has", "had", "under", "using", "through",
    "policy", "system", "serving", "runtime", "figure", "table", "equation", "introduction",
}

ALLOWED_BUCKETS = {
    "abstract",
    "paper_info",
    "overview",
    "background",
    "motivation",
    "method",
    "results",
    "conclusion",
}


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def keyword_tokens(text: str) -> list[str]:
    tokens = [token for token in normalize_text(text).split() if len(token) >= 4 and token not in STOPWORDS]
    return tokens[:12]


def canonical_section_name(name: str) -> str:
    lowered = name.lower().strip()
    lowered = re.sub(r"^\d+(?:\.\d+)*\s*", "", lowered)
    lowered = lowered.replace("autopoiesisoverview", "overview")
    lowered = lowered.replace("llm-driven", "llm driven")
    lowered = lowered.replace("论文基本信息", "paper info")
    mapping = [
        (("front matter", "references", "appendix"), "ignore"),
        (("abstract", "摘要"), "abstract"),
        (("paper info", "论文基本信息", "基本信息"), "paper_info"),
        (("introduction", "整体概括"), "overview"),
        (("background", "related work", "preliminaries", "背景", "预备知识", "前人工作", "基础概念"), "background"),
        (("motivation", "动机"), "motivation"),
        (("method", "workflow", "implementation", "architecture", "problem formulation", "evaluator", "synthesis configuration", "方法", "系统设计", "实现优化", "问题形式化", "双平面", "工作流"), "method"),
        (("experiment", "evaluation", "result", "analysis", "实验", "结果", "评估指标", "对比基线", "实验环境", "案例分析"), "results"),
        (("conclusion", "discussion", "limitation", "总结", "思考", "局限"), "conclusion"),
    ]
    for keys, label in mapping:
        if any(key in lowered for key in keys):
            return label
    return lowered


def fallback_coverage(info_points: list[dict], note_text: str) -> dict:
    lowered = normalize_text(note_text)
    items = []
    covered = 0
    for row in info_points:
        for point in row.get("info_points", []):
            tokens = keyword_tokens(point)
            token_hits = sum(1 for token in tokens if token in lowered)
            threshold = 1 if len(tokens) <= 3 else 2
            hit = 1 if token_hits >= threshold else 0
            covered += hit
            items.append(
                {
                    "paragraph_id": row.get("paragraph_id", ""),
                    "info_point": point,
                    "covered": hit,
                    "reason": f"fallback token match {token_hits}/{len(tokens)}" if tokens else "fallback no tokens",
                }
            )
    total = len(items)
    return {
        "items": items,
        "summary": {
            "covered_count": covered,
            "total_count": total,
            "coverage_ratio": round(covered / max(1, total), 3),
            "top_missing_points": [item["info_point"] for item in items if not item["covered"]][:5],
        },
    }


def fallback_placement(references: list[dict], note_text: str) -> dict:
    lowered = normalize_text(note_text)
    sections = {}
    current = None
    for line in note_text.splitlines():
        if line.startswith("## "):
            current = line.replace("## ", "", 1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    items = []
    covered = placement = interleaved = 0
    for ref in references:
        label_tokens = keyword_tokens(str(ref.get("label") or ref.get("reference_id") or ""))
        context_tokens = keyword_tokens(" ".join(ref.get("context") or []))
        hit = 1 if sum(1 for token in context_tokens[:6] if token in lowered) >= 1 else 0
        source_section = canonical_section_name(str(ref.get("section", "")))
        placement_ok = 0
        if hit:
            for section_name, section_lines in sections.items():
                if canonical_section_name(section_name) != source_section:
                    continue
                section_text = normalize_text("\n".join(section_lines))
                if sum(1 for token in context_tokens[:6] if token in section_text) >= 1:
                    placement_ok = 1
                    break
            if not placement_ok and sum(1 for token in label_tokens[:4] if token in lowered) >= 1:
                placement_ok = 1
        interleaved_ok = 1 if hit and "![](" in note_text else 0
        covered += hit
        placement += placement_ok
        interleaved += interleaved_ok
        items.append(
            {
                "reference_id": ref.get("reference_id", ""),
                "kind": ref.get("kind", ""),
                "covered": hit,
                "placement_ok": placement_ok,
                "interleaved_ok": interleaved_ok,
                "reason": "fallback token heuristic",
            }
        )
    total = len(items)
    return {
        "items": items,
        "summary": {
            "coverage_ratio": round(covered / max(1, total), 3),
            "placement_ratio": round(placement / max(1, total), 3),
            "interleaving_ratio": round(interleaved / max(1, total), 3),
            "top_placement_issues": [item["reference_id"] for item in items if not item["placement_ok"]][:5],
        },
    }


def aggregate_coverage(chunks: list[dict]) -> dict:
    items = []
    for chunk in chunks:
        items.extend(chunk.get("items", []))
    covered = sum(int(item.get("covered", 0)) for item in items)
    total = len(items)
    return {
        "items": items,
        "summary": {
            "covered_count": covered,
            "total_count": total,
            "coverage_ratio": round(covered / max(1, total), 3),
            "top_missing_points": [item.get("info_point", "") for item in items if not item.get("covered", 0)][:8],
        },
    }


def aggregate_placement(chunks: list[dict]) -> dict:
    items = []
    for chunk in chunks:
        items.extend(chunk.get("items", []))
    total = len(items)
    covered = sum(int(item.get("covered", 0)) for item in items)
    placement = sum(int(item.get("placement_ok", 0)) for item in items)
    interleaved = sum(int(item.get("interleaved_ok", 0)) for item in items)
    return {
        "items": items,
        "summary": {
            "coverage_ratio": round(covered / max(1, total), 3),
            "placement_ratio": round(placement / max(1, total), 3),
            "interleaving_ratio": round(interleaved / max(1, total), 3),
            "top_placement_issues": [item.get("reference_id", "") for item in items if not item.get("placement_ok", 0)][:8],
        },
    }


def fallback_length(source_metrics: dict, note_metrics: dict) -> dict:
    source_sections = source_metrics if isinstance(source_metrics, list) else source_metrics.get("section_metrics", [])
    note_sections = note_metrics if isinstance(note_metrics, list) else note_metrics.get("section_metrics", [])
    note_map: dict[str, dict] = {}
    for item in note_sections:
        canon = canonical_section_name(str(item.get("section", "")))
        current = note_map.setdefault(canon, {"section": canon, "paragraph_count": 0, "image_count": 0})
        current["paragraph_count"] += int(item.get("paragraph_count", 0))
        current["image_count"] += int(item.get("image_count", 0))
    source_map: dict[str, dict] = {}
    for item in source_sections:
        canon = canonical_section_name(str(item.get("section", "")))
        if canon not in ALLOWED_BUCKETS:
            continue
        current = source_map.setdefault(canon, {"section": canon, "paragraph_count": 0, "figure_count": 0, "table_count": 0})
        current["paragraph_count"] += int(item.get("paragraph_count", 0))
        current["figure_count"] += int(item.get("figure_count", 0))
        current["table_count"] += int(item.get("table_count", 0))
    section_scores = []
    ok = 0
    for canon, source in source_map.items():
        section_name = canon
        source_weight = int(source.get("paragraph_count", 0)) + int(source.get("figure_count", 0)) + int(source.get("table_count", 0))
        match = note_map.get(canon)
        note_weight = 0 if not match else int(match.get("paragraph_count", 0)) + int(match.get("image_count", 0))
        if source_weight == 0:
            distribution_ok = 1
        elif note_weight == 0:
            distribution_ok = 0
        else:
            ratio = note_weight / max(1, source_weight)
            distribution_ok = 1 if 0.2 <= ratio <= 3.5 else 0
        ok += distribution_ok
        section_scores.append(
            {
                "section": section_name,
                "distribution_ok": distribution_ok,
                "reason": f"fallback canonical ratio note/source={round(note_weight / max(1, source_weight), 2)}" if note_weight else f"fallback no note coverage for {canon}",
            }
        )
    total = len(section_scores)
    return {
        "section_scores": section_scores,
        "summary": {
            "distribution_ratio": round(ok / max(1, total), 3),
            "top_distribution_issues": [item["section"] for item in section_scores if not item["distribution_ok"]][:8],
            "overall_comment": "fallback heuristic comparison",
        },
    }


def average(items: list[float]) -> float:
    return round(sum(items) / max(1, len(items)), 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", help="Only evaluate one benchmark paper")
    parser.add_argument("--use-agent", action="store_true", help="Use agent for review chunks instead of deterministic fallback baseline")
    args = parser.parse_args()

    assets_root = settings.evaluation_assets_dir
    prompt_loader = PromptLoader(settings.prompt_dir)
    notes_root = settings.obsidian_notes_root
    evaluations: list[dict] = []

    papers = BENCHMARKS
    if args.paper_id:
        papers = [paper for paper in BENCHMARKS if paper["id"] == args.paper_id]
        if not papers:
            raise SystemExit(f"unknown paper id: {args.paper_id}")

    for paper in papers:
        note_path = find_note(notes_root, paper["short_id"])
        paper_root = assets_root / paper["id"]
        if not note_path or not paper_root.exists():
            evaluations.append({"id": paper["id"], "status": "missing"})
            continue
        note_text = note_path.read_text(encoding="utf-8")
        info_points = json.loads((paper_root / "paragraph_info_points.json").read_text(encoding="utf-8"))
        pdf_structure = json.loads((paper_root / "pdf_structure.json").read_text(encoding="utf-8"))
        note_metrics = build_note_metrics(note_text)
        swiftscholar_diff_path = paper_root / "evaluation" / "swiftscholar_structure_diff.json"
        swiftscholar_diff = (
            json.loads(swiftscholar_diff_path.read_text(encoding="utf-8"))
            if swiftscholar_diff_path.exists()
            else None
        )

        coverage_chunks = []
        flattened_points = [
            {"paragraph_id": row.get("paragraph_id", ""), "info_points": row.get("info_points", [])}
            for row in info_points
        ]
        for chunk in split_text_batches(flattened_points, 30):
            if args.use_agent:
                try:
                    payload = run_agent_prompt(
                        prompt_loader,
                        "benchmark_coverage_prompt_file",
                        substitutions={
                            "paper_title": paper["title"],
                            "info_points_payload": json.dumps(chunk, ensure_ascii=False, indent=2),
                            "note_text": note_text[:20000],
                        },
                    ).payload
                except Exception:
                    payload = fallback_coverage(chunk, note_text)
            else:
                payload = fallback_coverage(chunk, note_text)
            coverage_chunks.append(payload)
        coverage = aggregate_coverage(coverage_chunks)
        write_json(paper_root / "evaluation" / "coverage_review.json", coverage)

        placement_chunks = []
        for chunk in split_text_batches(pdf_structure["references"], 20):
            if args.use_agent:
                try:
                    payload = run_agent_prompt(
                        prompt_loader,
                        "benchmark_placement_prompt_file",
                        substitutions={
                            "paper_title": paper["title"],
                            "reference_payload": json.dumps(chunk, ensure_ascii=False, indent=2),
                            "note_text": note_text[:20000],
                        },
                    ).payload
                except Exception:
                    payload = fallback_placement(chunk, note_text)
            else:
                payload = fallback_placement(chunk, note_text)
            placement_chunks.append(payload)
        placement = aggregate_placement(placement_chunks)
        write_json(paper_root / "evaluation" / "placement_review.json", placement)
        if args.use_agent:
            try:
                length = run_agent_prompt(
                    prompt_loader,
                    "benchmark_length_prompt_file",
                    substitutions={
                        "paper_title": paper["title"],
                        "source_metrics_payload": json.dumps(pdf_structure["section_metrics"], ensure_ascii=False, indent=2),
                        "note_metrics_payload": json.dumps(note_metrics["section_metrics"], ensure_ascii=False, indent=2),
                    },
                ).payload
            except Exception:
                length = fallback_length(pdf_structure["section_metrics"], note_metrics["section_metrics"])
        else:
            length = fallback_length(pdf_structure["section_metrics"], note_metrics["section_metrics"])
        write_json(paper_root / "evaluation" / "length_review.json", length)

        evaluation = {
            "id": paper["id"],
            "title": paper["title"],
            "status": "ok",
            "note_path": str(note_path.relative_to(notes_root.parent)),
            "coverage_review": coverage,
            "placement_review": placement,
            "length_review": length,
            "swiftscholar_diff": swiftscholar_diff,
        }
        evaluations.append(evaluation)
        write_json(paper_root / "evaluation" / "latest.json", evaluation)

    coverage_scores = []
    placement_scores = []
    interleave_scores = []
    distribution_scores = []
    for item in evaluations:
        if item.get("status") != "ok":
            continue
        coverage_scores.append(float(item["coverage_review"]["summary"]["coverage_ratio"]))
        placement_scores.append(float(item["placement_review"]["summary"]["placement_ratio"]))
        interleave_scores.append(float(item["placement_review"]["summary"]["interleaving_ratio"]))
        distribution_scores.append(float(item["length_review"]["summary"]["distribution_ratio"]))

    report = {
        "per_paper": evaluations,
        "avg_coverage_ratio": average(coverage_scores),
        "avg_placement_ratio": average(placement_scores),
        "avg_interleaving_ratio": average(interleave_scores),
        "avg_distribution_ratio": average(distribution_scores),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
