from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from paper_queue.config import settings
from paper_queue.evaluation import find_note


BENCHMARKS = json.loads((BASE_DIR / "benchmarks" / "swiftscholar_benchmark.json").read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def note_structure(note_text: str) -> dict:
    headings = re.findall(r"^(##+)\s+(.+)$", note_text, flags=re.M)
    return {
        "heading_count": len(headings),
        "headings": [{"level": len(prefix), "text": text.strip()} for prefix, text in headings],
        "image_count": note_text.count("![]("),
        "paragraph_count": len([chunk for chunk in re.split(r"\n\s*\n", note_text) if chunk.strip()]),
    }


def major_swiftscholar_headings(snapshot: dict) -> list[str]:
    out = []
    for heading in snapshot.get("headings", []):
        text = heading.get("text", "").strip()
        if not text:
            continue
        if re.match(r"^\d+\.\s+", text):
            out.append(text)
    return out


def fine_swiftscholar_headings(snapshot: dict) -> list[str]:
    out = []
    for heading in snapshot.get("headings", []):
        text = heading.get("text", "").strip()
        if not text or len(text) > 80:
            continue
        if re.match(r"^\d+(?:\.\d+){1,2}\.\s+", text):
            out.append(text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id")
    args = parser.parse_args()

    papers = BENCHMARKS
    if args.paper_id:
        papers = [paper for paper in BENCHMARKS if paper["id"] == args.paper_id]
        if not papers:
            raise SystemExit(f"unknown paper id: {args.paper_id}")

    out = []
    for paper in papers:
        paper_root = BASE_DIR / "benchmarks" / "assets" / paper["id"]
        snapshot_path = paper_root / "swiftscholar_snapshot.json"
        note_path = find_note(settings.obsidian_notes_root, paper["short_id"])
        if not snapshot_path.exists() or not note_path:
            out.append({"id": paper["id"], "status": "missing"})
            continue
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        note_text = note_path.read_text(encoding="utf-8")
        note_info = note_structure(note_text)
        sw_headings = major_swiftscholar_headings(snapshot)
        sw_fine_headings = fine_swiftscholar_headings(snapshot)
        note_headings = [h["text"] for h in note_info["headings"]]
        out.append(
            {
                "id": paper["id"],
                "swiftscholar_major_heading_count": len(sw_headings),
                "swiftscholar_fine_heading_count": len(sw_fine_headings),
                "note_heading_count": len(note_headings),
                "swiftscholar_image_count": snapshot["image_count"],
                "note_image_count": note_info["image_count"],
                "swiftscholar_block_count": len(snapshot["blocks"]),
                "note_paragraph_count": note_info["paragraph_count"],
                "shared_headings": [h for h in note_headings if any(h in s or s in h for s in sw_headings)],
                "major_heading_gap": len(sw_headings) - len(note_headings),
            }
        )
        write_json(paper_root / "evaluation" / "swiftscholar_structure_diff.json", out[-1])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
