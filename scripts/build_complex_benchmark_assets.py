from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from paper_queue.config import settings
from paper_queue.evaluation import ensure_pdf, extract_pdf_assets, run_agent_prompt, split_batches
from paper_queue.prompt_loader import PromptLoader

BENCHMARK_PATH = BASE_DIR / "benchmarks" / "swiftscholar_benchmark.json"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fallback_batch(batch: list[dict]) -> list[dict]:
    items = []
    for item in batch:
        sentence = item["text"].split(". ")[0].strip()
        info_point = sentence if sentence else item["text"][:200]
        items.append(
            {
                "paragraph_id": item["paragraph_id"],
                "translation": item["text"][:220],
                "info_points": [info_point],
                "keywords": [],
            }
        )
    return items


def deterministic_batch(batch: list[dict]) -> list[dict]:
    items = []
    for item in batch:
        text = item["text"].strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if not sentences:
            sentences = [text]
        important = next((s for s in sentences if re.search(r"\d|%|latency|throughput|algorithm|policy|architecture|workflow|evaluation|result", s, re.I)), sentences[0])
        keywords = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)[:8]
        items.append(
            {
                "paragraph_id": item["paragraph_id"],
                "translation": text[:220],
                "info_points": [important[:300]],
                "keywords": keywords,
                "source_text": text,
            }
        )
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id", help="Only build assets for one benchmark paper")
    parser.add_argument("--use-agent", action="store_true", help="Use agent to enrich paragraph points")
    args = parser.parse_args()

    papers = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    if args.paper_id:
        papers = [paper for paper in papers if paper["id"] == args.paper_id]
        if not papers:
            raise SystemExit(f"unknown paper id: {args.paper_id}")
    prompt_loader = PromptLoader(settings.prompt_dir)
    assets_root = settings.evaluation_assets_dir
    batch_size = settings.evaluation_paragraph_batch_size

    for paper in papers:
        paper_root = assets_root / paper["id"]
        pdf_path = ensure_pdf(paper, paper_root)
        extracted = extract_pdf_assets(pdf_path)
        write_json(paper_root / "paper_meta.json", paper)
        write_json(paper_root / "pdf_structure.json", extracted)

        paragraph_assets: list[dict] = []
        batches = split_batches(extracted["paragraphs"], batch_size)
        for index, batch in enumerate(batches, start=1):
            batch_path = paper_root / "paragraph_batches" / f"batch-{index:03d}.json"
            if batch_path.exists():
                existing = json.loads(batch_path.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    paragraph_assets.extend(existing)
                    continue
            payload = [
                {
                    "paragraph_id": item["paragraph_id"],
                    "page": item["page"],
                    "section": item["section"],
                    "text": item["text"][: settings.evaluation_max_paragraph_chars],
                }
                for item in batch
            ]
            batch_payload = deterministic_batch(payload)
            if args.use_agent:
                try:
                    result = run_agent_prompt(
                        prompt_loader,
                        "benchmark_paragraph_points_prompt_file",
                        substitutions={
                            "paper_title": paper["title"],
                            "paragraph_payload": json.dumps(payload, ensure_ascii=False, indent=2),
                        },
                    )
                    if isinstance(result.payload, list):
                        batch_payload = result.payload
                except Exception:
                    batch_payload = fallback_batch(payload)
            write_json(batch_path, batch_payload)
            paragraph_assets.extend(batch_payload)

        write_json(paper_root / "paragraph_info_points.json", paragraph_assets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
