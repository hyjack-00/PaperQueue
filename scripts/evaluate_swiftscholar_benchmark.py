from __future__ import annotations

import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
BENCHMARKS = json.loads((BASE_DIR / "benchmarks" / "swiftscholar_benchmark.json").read_text())
NOTES_ROOT = BASE_DIR.parent / "obsidian_sync" / "paper"


def find_note(short_id: str) -> Path | None:
    matches = sorted(NOTES_ROOT.rglob(f"{short_id}*.md"), key=lambda p: p.stat().st_mtime)
    if matches:
        return matches[-1]
    tail = short_id.split("-")[-1].lower()
    fallback = sorted((p for p in NOTES_ROOT.rglob("*.md") if tail in p.stem.lower()), key=lambda p: p.stat().st_mtime)
    return fallback[-1] if fallback else None


def section_slice(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    remainder = text[start:]
    next_heading = re.search(r"\n##\s+[^\n]+", remainder[len(heading):])
    if not next_heading:
        return remainder
    return remainder[: len(heading) + next_heading.start()]


def score_structure(text: str, headings: list[str]) -> float:
    hits = sum(1 for heading in headings if heading in text)
    return hits / max(1, len(headings))


def score_coverage(text: str, checks: list[str]) -> float:
    lowered = text.lower()
    hits = 0
    for check in checks:
        alternatives = [alt.strip() for alt in check.split(" or ")]
        if any(alt.lower() in lowered for alt in alternatives):
            hits += 1
    return hits / max(1, len(checks))


def score_bibliography(text: str) -> float:
    section = section_slice(text, "## 论文基本信息")
    fields = ["Title", "Venue", "Year", "Authors", "Paper URL"]
    hits = sum(1 for field in fields if field in section)
    penalties = 0
    for noisy in ["repo", "university", "notebook", "archive_topic"]:
        if noisy.lower() in section.lower():
            penalties += 1
    raw = hits / len(fields)
    return max(0.0, raw - (0.1 * penalties))


def score_figures(text: str, expectations: list[dict[str, str]]) -> float:
    score = 0.0
    for expectation in expectations:
        section = section_slice(text, expectation["section"])
        if not section:
            continue
        if "![](" not in section:
            continue
        if expectation["keyword"].lower() in section.lower():
            score += 1.0
        else:
            score += 0.6
    return score / max(1, len(expectations))


def score_style(text: str) -> float:
    score = 0.0
    if "## TL;DR" in text:
        score += 0.25
    if "## 论文基本信息" in text:
        score += 0.25
    if "## 1. 整体概括" in text and "## 6. 总结与思考" in text:
        score += 0.25
    if len(re.findall(r"^## ", text, flags=re.M)) <= 8:
        score += 0.25
    return score


def main() -> int:
    per_paper: list[dict] = []
    for item in BENCHMARKS:
        note = find_note(item["short_id"])
        if not note:
            per_paper.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "status": "missing",
                    "coverage_score": 0.0,
                    "structure_score": 0.0,
                    "style_similarity_score": 0.0,
                    "bibliography_score": 0.0,
                    "figure_match_score": 0.0,
                }
            )
            continue
        text = note.read_text(encoding="utf-8")
        per_paper.append(
            {
                "id": item["id"],
                "title": item["title"],
                "status": "ok",
                "note_path": str(note.relative_to(NOTES_ROOT.parent)),
                "coverage_score": round(score_coverage(text, item["coverage_checks"]), 3),
                "structure_score": round(score_structure(text, item["expected_headings"]), 3),
                "style_similarity_score": round(score_style(text), 3),
                "bibliography_score": round(score_bibliography(text), 3),
                "figure_match_score": round(score_figures(text, item["figure_expectations"]), 3),
            }
        )

    def avg(key: str) -> float:
        return round(sum(item[key] for item in per_paper) / max(1, len(per_paper)), 3)

    payload = {
        "per_paper_scores": per_paper,
        "avg_coverage_score": avg("coverage_score"),
        "avg_structure_score": avg("structure_score"),
        "avg_style_similarity_score": avg("style_similarity_score"),
        "avg_bibliography_score": avg("bibliography_score"),
        "avg_figure_match_score": avg("figure_match_score"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
