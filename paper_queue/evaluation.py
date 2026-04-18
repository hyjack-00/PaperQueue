from __future__ import annotations

import json
import re
import shlex
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import requests

from .config import Settings, settings
from .prompt_loader import PromptLoader


SECTION_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*)\s+.+$")
INLINE_SECTION_HEADING_RE = re.compile(r"^(?:Abstract|References|Appendix)\b", re.I)
REFERENCE_RE = re.compile(
    r"\b(?P<kind>Figure|Fig\.|Table|Equation|Eq\.)\s*(?P<id>\d+(?:\.\d+)?|[IVX]+|\([^)]+\))",
    re.I,
)


@dataclass(slots=True)
class AgentEvalResult:
    payload: Any
    raw_text: str


def normalize_pdf_url(paper_url: str) -> str:
    if "/abs/" in paper_url:
        return paper_url.replace("/abs/", "/pdf/") + ".pdf" if not paper_url.endswith(".pdf") else paper_url
    return paper_url


def safe_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return text or "paper"


def _normalize_block_text(lines: list[str]) -> str:
    line_joined = " ".join(line.strip() for line in lines if line.strip())
    line_joined = re.sub(r"\s+", " ", line_joined).strip()
    line_joined = line_joined.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return line_joined


def is_heading_text(text: str) -> bool:
    if not text:
        return False
    if SECTION_HEADING_RE.match(text):
        return True
    if INLINE_SECTION_HEADING_RE.match(text):
        return True
    return False


def block_items_from_page(page: fitz.Page) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        sizes: list[float] = []
        for line in block.get("lines", []):
            parts = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if text.strip():
                    parts.append(text)
                    sizes.append(float(span.get("size", 0.0)))
            line_text = "".join(parts).strip()
            if line_text:
                lines.append(line_text)
        if not lines:
            continue
        text = _normalize_block_text(lines)
        max_size = max(sizes) if sizes else 0.0
        min_size = min(sizes) if sizes else 0.0
        items.append({"text": text, "max_size": max_size, "min_size": min_size})
    return items


def page_paragraph_items(page: fitz.Page) -> list[dict[str, Any]]:
    blocks = block_items_from_page(page)
    merged: list[dict[str, Any]] = []
    buffer: list[dict[str, Any]] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = " ".join(item["text"] for item in buffer).strip()
        text = re.sub(r"\s+", " ", text)
        merged.append(
            {
                "text": text,
                "max_size": max(item["max_size"] for item in buffer),
                "min_size": min(item["min_size"] for item in buffer),
                "is_heading": False,
            }
        )
        buffer = []

    for item in blocks:
        text = item["text"]
        max_size = item["max_size"]
        if len(text) < 4:
            continue
        if max_size <= 7.2 and len(text) < 80:
            continue
        if re.fullmatch(r"[0-9.\- ]+", text):
            continue
        if text.startswith("arXiv:"):
            continue
        is_heading = is_heading_text(text) or (len(text) < 80 and max_size >= 11.0)
        if is_heading:
            flush_buffer()
            merged.append({**item, "is_heading": True})
            continue
        if len(text) < 40:
            continue
        buffer.append(item)
        current_text = " ".join(entry["text"] for entry in buffer)
        if len(current_text) >= 900 or text.endswith((".", "?", "!", ":")):
            flush_buffer()
    flush_buffer()
    return merged


def detect_sections(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current = {"title": "Front Matter", "level": 1, "start_index": 0}
    sections.append(current)
    for idx, item in enumerate(paragraphs):
        text = item["text"]
        if item.get("is_heading") or (len(text) < 120 and is_heading_text(text)):
            level = text.count(".") + 1 if SECTION_HEADING_RE.match(text) else 1
            current = {"title": text, "level": level, "start_index": idx}
            sections.append(current)
    for i, section in enumerate(sections):
        next_start = sections[i + 1]["start_index"] if i + 1 < len(sections) else len(paragraphs)
        section["end_index"] = next_start
    return sections


def assign_section(index: int, sections: list[dict[str, Any]]) -> str:
    current = sections[0]["title"]
    for section in sections:
        if section["start_index"] <= index < section["end_index"]:
            current = section["title"]
            break
    return current


def extract_pdf_assets(pdf_path: Path) -> dict[str, Any]:
    doc = fitz.open(pdf_path)
    paragraphs: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    page_image_counts: Counter[int] = Counter()

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_image_counts[page_index + 1] = len(page.get_images(full=True))
        for item in page_paragraph_items(page):
            text = item["text"]
            max_size = item["max_size"]
            min_size = item["min_size"]
            if len(text) < 4:
                continue
            is_heading = bool(item.get("is_heading"))
            if not is_heading and len(text) < 40:
                continue
            paragraphs.append(
                {
                    "paragraph_id": f"p{page_index + 1:02d}-{len(paragraphs) + 1:04d}",
                    "page": page_index + 1,
                    "text": text,
                    "font_max_size": round(max_size, 1),
                    "font_min_size": round(min_size, 1),
                    "is_heading": is_heading,
                }
            )

    sections = detect_sections(paragraphs)
    for idx, item in enumerate(paragraphs):
        item["section"] = assign_section(idx, sections)

    for idx, item in enumerate(paragraphs):
        for match in REFERENCE_RE.finditer(item["text"]):
            kind_raw = match.group("kind").lower()
            kind = "figure" if kind_raw.startswith("fig") else "table" if kind_raw.startswith("table") else "equation"
            context = paragraphs[max(0, idx - 1): min(len(paragraphs), idx + 2)]
            references.append(
                {
                    "reference_id": f"{kind}:{match.group('id')}",
                    "kind": kind,
                    "label": match.group(0),
                    "page": item["page"],
                    "section": item["section"],
                    "context": [entry["text"] for entry in context],
                }
            )

    section_metrics: list[dict[str, Any]] = []
    for section in sections:
        section_paragraphs = paragraphs[section["start_index"]: section["end_index"]]
        pages = {entry["page"] for entry in section_paragraphs}
        ref_slice = [ref for ref in references if ref["section"] == section["title"]]
        section_metrics.append(
            {
                "section": section["title"],
                "paragraph_count": len(section_paragraphs),
                "figure_count": sum(1 for ref in ref_slice if ref["kind"] == "figure"),
                "table_count": sum(1 for ref in ref_slice if ref["kind"] == "table"),
                "equation_count": sum(1 for ref in ref_slice if ref["kind"] == "equation"),
                "image_count": sum(page_image_counts[page] for page in pages),
            }
        )

    return {
        "paragraphs": paragraphs,
        "sections": sections,
        "references": references,
        "section_metrics": section_metrics,
    }


def split_batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def split_text_batches(items: list[Any], batch_size: int) -> list[list[Any]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def build_note_metrics(note_text: str) -> dict[str, Any]:
    sections = re.split(r"(?=^##\s+)", note_text, flags=re.M)
    metrics: list[dict[str, Any]] = []
    for section in sections:
        if not section.strip().startswith("## "):
            continue
        lines = section.strip().splitlines()
        title = lines[0].replace("##", "", 1).strip()
        body = "\n".join(lines[1:]).strip()
        chunks = [chunk for chunk in re.split(r"\n\s*\n", body) if chunk.strip()]
        paragraph_count = len(chunks)
        image_positions = [idx for idx, chunk in enumerate(chunks) if "![](" in chunk]
        text_before_images = sum(1 for idx, chunk in enumerate(chunks) if idx not in image_positions and idx < (image_positions[0] if image_positions else 10**9))
        text_after_images = sum(1 for idx, chunk in enumerate(chunks) if idx not in image_positions and idx > (image_positions[-1] if image_positions else -1))
        metrics.append(
            {
                "section": title,
                "paragraph_count": paragraph_count,
                "image_count": body.count("![]("),
                "text_before_first_image": text_before_images,
                "text_after_last_image": text_after_images,
                "interleaving_transitions": max(0, len(image_positions) - 1),
            }
        )
    return {"section_metrics": metrics}


def find_note(notes_root: Path, short_id: str) -> Path | None:
    matches = sorted(notes_root.rglob(f"{short_id}*.md"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def find_swiftscholar_pdf(paper_title: str, pdf_dir: Path) -> Path | None:
    if not pdf_dir.exists():
        return None
    normalized_title = re.sub(r"[^a-z0-9]+", " ", paper_title.lower()).strip()
    title_tokens = [token for token in normalized_title.split() if len(token) >= 4]
    best: tuple[int, Path] | None = None
    for candidate in pdf_dir.glob("*.pdf"):
        name = re.sub(r"[^a-z0-9]+", " ", candidate.stem.lower()).strip()
        score = sum(1 for token in title_tokens if token in name)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def parse_first_json(text: str) -> Any:
    text = text.strip()
    for candidate in (text, re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for index, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in agent output")


def run_agent_prompt(
    prompt_loader: PromptLoader,
    prompt_name: str,
    *,
    substitutions: dict[str, str],
    config: Settings = settings,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> AgentEvalResult:
    template_file = getattr(config, prompt_name)
    prompt_text = prompt_loader.load(template_file, **substitutions)
    command = (
        f"{config.claude_glm_command} -p "
        f"{shlex.quote(prompt_text)} "
        f"--model {shlex.quote(config.claude_model)} "
        "--output-format json"
    )
    from .runtime import Runtime

    runtime = Runtime(config)
    result = runtime.run_shell(
        command,
        cwd=cwd,
        timeout=config.evaluation_agent_timeout_seconds if timeout is None else timeout,
    )
    raw_text = (result.stdout or result.stderr).strip()
    payload = parse_first_json(raw_text)
    return AgentEvalResult(payload=payload, raw_text=raw_text)


def ensure_pdf(paper: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{safe_slug(paper['short_id'])}.pdf"
    if pdf_path.exists():
        return pdf_path
    url = normalize_pdf_url(paper["paper_url"])
    response = requests.get(
        url,
        timeout=120,
        stream=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    with pdf_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if chunk:
                handle.write(chunk)
    return pdf_path
