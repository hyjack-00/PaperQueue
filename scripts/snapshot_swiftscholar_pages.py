from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from paper_queue.config import settings
from paper_queue.evaluation import block_items_from_page, find_swiftscholar_pdf


BENCHMARKS = json.loads((BASE_DIR / "benchmarks" / "swiftscholar_benchmark.json").read_text(encoding="utf-8"))


MENU_PATTERNS = (
    "管理收藏夹",
    "思维导图",
    "论文图片分析",
    "相似论文推荐",
    "TL;DR 与摘要",
)


def classify_heading(text: str, max_size: float) -> str | None:
    text = text.strip()
    if not text:
        return None
    if any(token in text for token in MENU_PATTERNS):
        return None
    if max_size >= 20:
        return "h2"
    if max_size >= 15 and (re.match(r"^\d+(?:\.\d+)*\.", text) or len(text) <= 40):
        return "h3"
    if re.match(r"^(TL;DR|摘要|论文基本信息|整体概括|背景与动机|方法与系统设计|实验设置|结果与分析|总结与思考)", text):
        return "h3"
    return None


def snapshot_from_pdf(pdf_path: Path) -> dict:
    doc = fitz.open(pdf_path)
    headings = []
    blocks = []
    image_count = 0
    title = ""
    for page_index in range(len(doc)):
        page = doc[page_index]
        image_count += len(page.get_images(full=True))
        for item in block_items_from_page(page):
            text = item["text"]
            level = classify_heading(text, item["max_size"])
            if not title and item["max_size"] >= 20 and len(text) >= 20:
                title = text
            if level:
                headings.append(
                    {
                        "level": level,
                        "text": text,
                        "page": page_index + 1,
                    }
                )
            else:
                blocks.append(
                    {
                        "kind": "p",
                        "page": page_index + 1,
                        "text": text[:300],
                    }
                )
    return {
        "title": title or (headings[0]["text"] if headings else pdf_path.stem),
        "headings": headings,
        "image_count": image_count,
        "images": [],
        "blocks": blocks[:400],
        "source_pdf": str(pdf_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-id")
    args = parser.parse_args()

    papers = BENCHMARKS
    if args.paper_id:
        papers = [paper for paper in BENCHMARKS if paper["id"] == args.paper_id]
        if not papers:
            raise SystemExit(f"unknown paper id: {args.paper_id}")

    assets_root = BASE_DIR / "benchmarks" / "assets"
    for paper in papers:
        paper_root = assets_root / paper["id"]
        paper_root.mkdir(parents=True, exist_ok=True)
        pdf_path = find_swiftscholar_pdf(paper["title"], settings.evaluation_swiftscholar_pdf_dir)
        if not pdf_path:
            raise SystemExit(f"missing swiftscholar pdf for {paper['id']}")
        parsed = snapshot_from_pdf(pdf_path)
        (paper_root / "swiftscholar_snapshot.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
