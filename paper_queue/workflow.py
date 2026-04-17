from __future__ import annotations

import hashlib
import json
from html import unescape
import io
import re
import tarfile
import fitz
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .runtime import Runtime


LogFn = Callable[[str, str, str], None]
NotebookFn = Callable[[str, str], None]
PaperTitleFn = Callable[[str], None]
AssetList = list[dict[str, str]]

ROUTE_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "using", "use", "via", "toward", "towards",
    "based", "study", "paper", "toward", "through", "without", "under", "over", "into",
    "this", "that", "these", "those", "are", "our", "their", "its", "your", "new", "via",
}

ROUTE_TOPIC_MAP: list[tuple[str, set[str]]] = [
    (
        "Kernels Engineering",
        {
            "kernel", "kernels", "cuda", "npu", "gpu", "operator", "operators",
            "compiler", "codegen", "triton", "ptx", "fusion", "scheduling",
        },
    ),
    (
        "System Performance",
        {
            "performance", "latency", "throughput", "serving", "system", "systems",
            "runtime", "profiling", "parallelism", "inference", "training", "memory-bandwidth",
        },
    ),
    (
        "Agent Harness Evaluation",
        {
            "agent", "agents", "coding", "code", "benchmark", "evaluation", "evaluate",
            "harness", "swe", "software", "engineering", "developer", "repo", "repository",
            "prompt", "terminal", "programming",
        },
    ),
    (
        "Ops4LLM",
        {
            "aiops", "ops", "llmops", "microservice", "incident", "operations",
            "sre", "devops", "observability", "service", "services", "cloud", "deployment",
        },
    ),
    (
        "Automated Tuning",
        {
            "tuning", "autotuning", "auto-tuning", "optimization", "search", "scheduler",
            "sparsity", "quantization", "calibration", "compilation", "hyperparameter",
        },
    ),
    (
        "LLM Memory, Context, and Retrieval",
        {
            "memory", "context", "retrieval", "rag", "long", "sequence", "cache",
            "attention", "context-window", "indexing",
        },
    ),
]


TERM_PREFERENCES: list[tuple[str, str]] = [
    (r"(?<![A-Za-z])代码智能体(?![A-Za-z])", "coding agent"),
    (r"(?<![A-Za-z])编码智能体(?![A-Za-z])", "coding agent"),
    (r"(?<![A-Za-z])提示词(?![A-Za-z])", "prompt"),
    (r"(?<![A-Za-z])测试控制流/脚手架(?![A-Za-z])", "harness"),
    (r"(?<![A-Za-z])测试脚手架(?![A-Za-z])", "harness"),
    (r"(?<![A-Za-z])基准测试(?![A-Za-z])", "benchmark"),
    (r"(?<![A-Za-z])离线评估(?![A-Za-z])", "offline evaluation"),
    (r"(?<![A-Za-z])在线 A/B 测试(?![A-Za-z])", "online A/B test"),
]


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _clean_source_title(title: str) -> str:
    title = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
    title = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", title).strip()
    title = title.strip("*").strip()
    title = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]\.?$", "", title).strip()
    return title


def _clean_metadata_text(value: str, default: str = "") -> str:
    cleaned = _clean_source_title(value or "")
    lowered = cleaned.lower()
    if lowered in {
        "not available in the provided sources",
        "not available",
        "n/a",
        "none",
        "unknown",
    }:
        return default
    return cleaned or default


def _clean_inline_citations(text: str) -> str:
    cleaned = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.M)
    return cleaned


def _strip_generic_preface(text: str) -> str:
    patterns = [
        r"^这是一份基于.*?中文阅读笔记[:：]?\s*",
        r"^以下是.*?阅读笔记[:：]?\s*",
        r"^下面是.*?阅读笔记[:：]?\s*",
    ]
    cleaned = text.strip()
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.S)
    return cleaned.strip()


def _normalize_heading_spacing(text: str) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    return cleaned + "\n"


def _apply_terminology_preferences(text: str) -> str:
    cleaned = text
    for pattern, replacement in TERM_PREFERENCES:
        cleaned = re.sub(pattern, replacement, cleaned)
    return cleaned


def _collapse_duplicate_terms(text: str) -> str:
    cleaned = text
    duplicate_patterns = [
        r"\b(monorepo|benchmark|prompt|harness|solve rate|offline evaluation|online A/B test|coding agent|foundation model|baseline)（\1）",
        r"\b(monorepo|benchmark|prompt|harness|solve rate|offline evaluation|online A/B test|coding agent|foundation model|baseline) \(\1\)",
    ]
    for pattern in duplicate_patterns:
        cleaned = re.sub(pattern, r"\1", cleaned, flags=re.I)
    return cleaned


def _polish_notes_markdown(text: str) -> str:
    cleaned = _clean_inline_citations(text or "")
    cleaned = _strip_generic_preface(cleaned)
    cleaned = _apply_terminology_preferences(cleaned)
    cleaned = _collapse_duplicate_terms(cleaned)
    cleaned = _normalize_heading_spacing(cleaned)
    return cleaned


def _slug(value: str) -> str:
    value = re.sub(r'[\\/:?*"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace(" ", "-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:80].strip("-_") or "paper"


def _short_title_slug(title: str) -> str:
    cleaned = _clean_source_title(title or "")
    if not cleaned:
        return "paper"
    primary = re.split(r"[:：]|\\s+-\\s+", cleaned, maxsplit=1)[0].strip() or cleaned
    tokens = re.findall(r"[A-Za-z0-9]+", primary)
    if not tokens:
        return _slug(primary)
    compact = "-".join(tokens[:4])
    return _slug(compact)


def _canonical_paper_key(title: str) -> str:
    return _short_title_slug(title).lower()


def _source_fingerprint(input_text: str, paper_url: str, source_id: str, paper_title: str) -> str:
    payload = "||".join([input_text.strip(), paper_url.strip(), source_id.strip(), _canonical_paper_key(paper_title)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


KNOWN_VENUES = [
    "ICLR", "NeurIPS", "ICML", "ACL", "EMNLP", "NAACL", "COLM", "CVPR", "ECCV",
    "ICCV", "OSDI", "SOSP", "NSDI", "ATC", "ASPLOS", "SIGCOMM", "EuroSys", "FAST",
    "MICRO", "HPCA", "ISCA", "KDD", "WWW", "SIGIR", "AAAI", "IJCAI",
]


def _normalize_venue_name(value: str) -> str:
    cleaned = _clean_metadata_text(value or "", default="arXiv")
    if not cleaned:
        return "arXiv"
    accepted_match = re.search(r"accepted at\s+(.+)", cleaned, flags=re.I)
    if accepted_match:
        accepted_text = accepted_match.group(1)
        for venue in KNOWN_VENUES:
            if re.search(rf"\b{re.escape(venue)}\b", accepted_text, flags=re.I):
                return venue
    for venue in KNOWN_VENUES:
        if re.search(rf"\b{re.escape(venue)}\b", cleaned, flags=re.I):
            return venue
    if "arxiv" in cleaned.lower():
        return "arXiv"
    return cleaned


def _summarize_institutions(value: str) -> str:
    cleaned = _clean_metadata_text(value or "", default="")
    if not cleaned or cleaned in {"未知", "论文未明确说明"}:
        return "论文未明确说明"
    parts = [part.strip() for part in re.split(r"[;\n]|(?:\s{2,})", cleaned) if part.strip()]
    if not parts:
        return cleaned
    important = [
        part for part in parts
        if any(token in part.lower() for token in [
            "inc", "corp", "google", "meta", "microsoft", "openai", "anthropic",
            "nvidia", "amazon", "apple", "bytedance", "alibaba", "tencent",
        ])
    ]
    if len(parts) <= 2:
        chosen = parts
    elif important:
        chosen = [parts[0], *[part for part in important if part != parts[0]]]
    else:
        chosen = [parts[0]]
    seen: list[str] = []
    for item in chosen:
        if item not in seen:
            seen.append(item)
    return " / ".join(seen)


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)]+", text)
    return match.group(0) if match else None


def _extract_field(patterns: list[str], text: str, default: str = "") -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip().strip(".")
    return default


def _parse_nlm_query_output(stdout: str) -> dict:
    payload = json.loads(stdout)
    return payload["value"] if isinstance(payload, dict) and "value" in payload else payload


def _route_tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}|[\u4e00-\u9fff]{2,}", text.lower())
    tokens: set[str] = set()
    for token in raw:
        if token in ROUTE_STOPWORDS:
            continue
        if len(token) <= 2 and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        tokens.add(token)
        if "-" in token:
            tokens.update(part for part in token.split("-") if part and part not in ROUTE_STOPWORDS)
    return tokens


def _overlap_score(source_tokens: set[str], target_tokens: set[str]) -> float:
    if not source_tokens or not target_tokens:
        return 0.0
    overlap = source_tokens & target_tokens
    if not overlap:
        return 0.0
    rare_bonus = sum(1.0 if len(token) > 6 else 0.5 for token in overlap)
    ratio_bonus = len(overlap) / max(3, len(source_tokens))
    return len(overlap) + rare_bonus + ratio_bonus


def _fetch_arxiv_title(url: str) -> str:
    if "arxiv.org" not in url:
        return ""
    request = Request(url, headers={"User-Agent": "paper-queue/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except (TimeoutError, URLError, OSError):
        return ""
    meta_match = re.search(
        r'<meta\s+name="citation_title"\s+content="([^"]+)"',
        html,
        flags=re.I,
    )
    if meta_match:
        return _clean_source_title(unescape(meta_match.group(1)))
    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if not title_match:
        return ""
    title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
    title = re.sub(r"\s*\|\s*arXiv.*$", "", title, flags=re.I).strip()
    return _clean_source_title(title)


def _fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "paper-queue/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (TimeoutError, URLError, OSError):
        return ""


def _extract_meta_content(html: str, names: list[str]) -> str:
    for name in names:
        patterns = [
            rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]+)"',
            rf'<meta\s+property="{re.escape(name)}"\s+content="([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.I)
            if match:
                return unescape(match.group(1)).strip()
    return ""


def _suggest_topic_notebook(subject_text: str) -> tuple[str, list[str]]:
    tokens = _route_tokens(subject_text)
    best_title = "Agent Harness Evaluation"
    best_overlap: list[str] = []
    for title, keywords in ROUTE_TOPIC_MAP:
        overlap = sorted(tokens & keywords)
        if len(overlap) > len(best_overlap):
            best_title = title
            best_overlap = overlap
    return best_title, best_overlap


def _load_taxonomy_topics(taxonomy_note: Path) -> list[str]:
    if not taxonomy_note.exists():
        return [title for title, _ in ROUTE_TOPIC_MAP]
    topics: list[str] = []
    in_canonical = False
    for raw_line in taxonomy_note.read_text().splitlines():
        line = raw_line.strip()
        if line == '## Canonical Routing Topics':
            in_canonical = True
            continue
        if in_canonical and line.startswith('## ') and line != '## Canonical Routing Topics':
            break
        if in_canonical and line.startswith('### '):
            topic = re.sub(r'^###\s*\d+\.\s*', '', line).strip()
            if topic:
                topics.append(topic)
    return topics or [title for title, _ in ROUTE_TOPIC_MAP]


def _infer_paper_archetype(subject_text: str) -> str:
    tokens = _route_tokens(subject_text)
    if {"benchmark", "evaluation", "agent", "harness"} & tokens:
        return "evaluation"
    if {"safety", "risk", "attack", "chaos"} & tokens:
        return "safety"
    if {"tuning", "autotuning", "optimization", "search"} & tokens:
        return "tuning"
    if {"serving", "runtime", "latency", "throughput", "system", "systems"} & tokens:
        return "systems"
    if {"memory", "context", "retrieval", "rag"} & tokens:
        return "retrieval"
    return "general"


@dataclass(slots=True)
class PaperResult:
    status: str
    paper_title: str
    canonical_paper_key: str
    source_fingerprint: str
    framework_version: str
    output_path: str
    summary: str
    error: str


@dataclass(slots=True)
class OutputPlan:
    target: Path
    relative_output: Path
    assets_dir: Path
    relative_assets_dir: Path
    taxonomy_topic: str


class PaperWorkflow:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime

    def execute(
        self,
        job: dict,
        log: LogFn,
        *,
        set_notebook: NotebookFn | None = None,
        set_paper_title: PaperTitleFn | None = None,
    ) -> PaperResult:
        self._resolve_notebook(job, log, set_notebook=set_notebook, set_paper_title=set_paper_title)
        source_info = self._ensure_source(job, log)
        metadata = self._query_metadata(job["notebook_id"], source_info["source_id"], log)
        metadata = self._fallback_metadata(job, source_info, metadata, log)
        metadata = self._validate_metadata(metadata)
        if set_paper_title:
            set_paper_title(metadata["paper_title"])
        fingerprint = _source_fingerprint(
            str(job.get("input_text") or ""),
            source_info.get("paper_url") or metadata.get("paper_url") or "",
            source_info.get("source_id") or "",
            metadata["paper_title"],
        )
        archetype = _infer_paper_archetype(
            " ".join(
                part
                for part in [
                    str(job.get("input_text") or ""),
                    str(job.get("paper_title") or ""),
                    str(metadata.get("paper_title") or ""),
                    str(job.get("notebook_title") or ""),
                ]
                if part
            )
        )
        notes = self._query_notes(job["notebook_id"], source_info["source_id"], log, archetype=archetype)
        last_error = "git push failed"
        for attempt in range(1, 4):
            self._sync_repo(log, attempt=attempt)
            archive_topic = self._resolve_archive_topic(job, metadata, notes, log)
            output_plan = self._resolve_output_target(job, metadata, archive_topic)
            assets = self._extract_figures(job, source_info, output_plan, log)
            note_content = self._build_note_content(job, source_info, metadata, notes, assets=assets, archive_topic=archive_topic)
            relative_output = self._write_note_to_repo(output_plan, note_content, log)
            commit_message = f"Add paper note: {metadata['paper_title'] or relative_output.stem}"
            commit_result = self._commit_note(relative_output, commit_message, log)
            if commit_result == "noop":
                return PaperResult(
                    status="completed",
                    paper_title=metadata["paper_title"],
                    canonical_paper_key=_canonical_paper_key(metadata["paper_title"]),
                    source_fingerprint=fingerprint,
                    framework_version=self.runtime.config.framework_version,
                    output_path=relative_output.as_posix(),
                    summary=notes.splitlines()[0][:240] if notes else metadata["paper_title"],
                    error="",
                )
            push_result = self.runtime.run(
                [
                    "git",
                    "-C",
                    str(self.runtime.config.obsidian_sync_repo),
                    "push",
                    "origin",
                    self.runtime.config.obsidian_sync_branch,
                ],
                timeout=120.0,
            )
            if push_result.ok:
                log("git_push", f"Pushed {relative_output.as_posix()} to origin/{self.runtime.config.obsidian_sync_branch}", "INFO")
                return PaperResult(
                    status="completed",
                    paper_title=metadata["paper_title"],
                    canonical_paper_key=_canonical_paper_key(metadata["paper_title"]),
                    source_fingerprint=fingerprint,
                    framework_version=self.runtime.config.framework_version,
                    output_path=relative_output.as_posix(),
                    summary=notes.splitlines()[0][:240] if notes else metadata["paper_title"],
                    error="",
                )
            last_error = (push_result.stderr or push_result.stdout).strip() or "git push failed"
            log("git_push", f"Push attempt {attempt} failed: {last_error}", "WARN")
            if attempt >= 3:
                break
        raise RuntimeError(last_error)

    def _resolve_notebook(
        self,
        job: dict,
        log: LogFn,
        *,
        set_notebook: NotebookFn | None = None,
        set_paper_title: PaperTitleFn | None = None,
    ) -> None:
        manual_notebook_id = str(job.get("notebook_id") or "").strip()
        manual_notebook_title = str(job.get("notebook_title") or "").strip()
        if manual_notebook_id and manual_notebook_title:
            log("routing", f"Using manually selected notebook '{manual_notebook_title}'", "INFO")
            return

        subject_text = str(job["input_text"]).strip()
        if _is_url(subject_text):
            extracted_title = _fetch_arxiv_title(subject_text)
            if extracted_title:
                subject_text = extracted_title
                if set_paper_title:
                    set_paper_title(extracted_title)
                log("routing", f"Resolved routing title: {extracted_title}", "INFO")

        notebooks, error = self.runtime.notebook_list()
        if error:
            raise RuntimeError(error)

        candidates = [item for item in notebooks if str(item.get("title") or "").strip()]
        subject_tokens = _route_tokens(subject_text)
        scored: list[tuple[float, dict[str, str], str]] = []
        for item in candidates:
            title_tokens = _route_tokens(item["title"])
            score = _overlap_score(subject_tokens, title_tokens)
            if score <= 0:
                continue
            scored.append((score, item, f"title overlap: {', '.join(sorted(subject_tokens & title_tokens)[:5])}"))
        scored.sort(key=lambda value: value[0], reverse=True)

        augmented: list[tuple[float, dict[str, str], str]] = []
        for base_score, item, reason in scored[:3]:
            summary, _ = self.runtime.notebook_summary(item["id"])
            summary_tokens = _route_tokens(summary or "")
            score = base_score + (_overlap_score(subject_tokens, summary_tokens) * 0.35)
            augmented.append((score, item, reason))
        if augmented:
            augmented.sort(key=lambda value: value[0], reverse=True)
            best_score, best_item, reason = augmented[0]
            if best_score >= 1.8:
                job["notebook_id"] = best_item["id"]
                job["notebook_title"] = best_item["title"]
                if set_notebook:
                    set_notebook(best_item["id"], best_item["title"])
                log("routing", f"Reused notebook '{best_item['title']}' ({reason})", "INFO")
                return

        new_title, overlap = _suggest_topic_notebook(subject_text)
        existing = next((item for item in candidates if item["title"] == new_title), None)
        if existing:
            job["notebook_id"] = existing["id"]
            job["notebook_title"] = existing["title"]
            if set_notebook:
                set_notebook(existing["id"], existing["title"])
            log("routing", f"Reused notebook '{existing['title']}' via topic fallback", "INFO")
            return

        created, error = self.runtime.create_notebook(new_title)
        if error or not created:
            raise RuntimeError(error or "failed to create notebook")
        job["notebook_id"] = created["id"]
        job["notebook_title"] = created["title"]
        if set_notebook:
            set_notebook(created["id"], created["title"])
        detail = ", ".join(overlap[:5]) if overlap else "default topic"
        log("routing", f"Created notebook '{created['title']}' from topic hints: {detail}", "INFO")

    def _ensure_source(self, job: dict, log: LogFn) -> dict[str, str]:
        input_text = str(job["input_text"]).strip()
        before = self._source_list(job["notebook_id"])
        before_ids = {item["id"] for item in before}
        if _is_url(input_text):
            url = input_text
            log("source_add", f"Adding source URL {url}", "INFO")
            result = self.runtime.run(
                [
                    "nlm",
                    "source",
                    "add",
                    str(job["notebook_id"]),
                    "--url",
                    url,
                    "--wait",
                    "--wait-timeout",
                    "600",
                ],
                timeout=660.0,
            )
            if not result.ok and "arxiv.org/abs/" in url:
                pdf_url = self._pdf_candidate_url(url)
                log("source_add", f"Primary arXiv URL failed, retrying with PDF URL {pdf_url}", "WARN")
                result = self.runtime.run(
                    [
                        "nlm",
                        "source",
                        "add",
                        str(job["notebook_id"]),
                        "--url",
                        pdf_url,
                        "--wait",
                        "--wait-timeout",
                        "600",
                    ],
                    timeout=660.0,
                )
                url = pdf_url
            if not result.ok:
                raise RuntimeError((result.stderr or result.stdout).strip() or "failed to add source")
            source_id = _extract_field([r"Source ID:\s*([^\s]+)"], result.stdout)
            title = _extract_field([r"Added source:\s*(.+?)\s+\(ready\)"], result.stdout)
            if source_id:
                return {
                    "source_id": source_id,
                    "source_title": _clean_source_title(title or input_text),
                    "paper_url": url,
                }
            after = self._source_list(job["notebook_id"])
            for item in reversed(after):
                if item["id"] not in before_ids and item.get("url") == url:
                    return {
                        "source_id": item["id"],
                        "source_title": _clean_source_title(item.get("title") or input_text),
                        "paper_url": url,
                    }
            raise RuntimeError("source add succeeded but new source could not be identified")

        log("research", f"Starting research import for query: {input_text}", "INFO")
        result = self.runtime.run(
            [
                "nlm",
                "research",
                "start",
                input_text,
                "--notebook-id",
                str(job["notebook_id"]),
                "--auto-import",
            ],
            timeout=900.0,
        )
        if not result.ok:
            raise RuntimeError((result.stderr or result.stdout).strip() or "research start failed")
        after = self._source_list(job["notebook_id"])
        for item in reversed(after):
            if item["id"] not in before_ids:
                return {
                    "source_id": item["id"],
                    "source_title": _clean_source_title(item.get("title") or input_text),
                    "paper_url": item.get("url") or "",
                }
        raise RuntimeError("research completed but imported source could not be identified")

    def _source_list(self, notebook_id: str) -> list[dict]:
        result = self.runtime.run(["nlm", "source", "list", str(notebook_id), "--json"], timeout=30.0)
        if not result.ok:
            raise RuntimeError((result.stderr or result.stdout).strip() or "failed to list sources")
        payload = json.loads(result.stdout)
        return [item for item in payload if isinstance(item, dict)]

    def _query_metadata(self, notebook_id: str, source_id: str, log: LogFn) -> dict[str, str]:
        log("metadata", f"Querying metadata for source {source_id}", "INFO")
        question = (
            "Extract the following metadata from this paper with high precision: full paper title, conference or journal name "
            "(prefer accepted venue if stated, otherwise use arXiv), publication year, author list, author affiliations, "
            "original paper URL, and GitHub repository link if available. Return concise structured text with one field per line."
        )
        result = self.runtime.run(
            [
                "nlm",
                "notebook",
                "query",
                str(notebook_id),
                "--source-ids",
                source_id,
                "--timeout",
                "180",
                "--json",
                question,
            ],
            timeout=210.0,
        )
        if not result.ok:
            raise RuntimeError((result.stderr or result.stdout).strip() or "metadata query failed")
        payload = _parse_nlm_query_output(result.stdout)
        answer = str(payload.get("answer") or "")
        paper_title = _clean_metadata_text(
            _extract_field([r"Full paper title:\**\s*(.+)", r"Title:\**\s*(.+)"], answer, ""),
            default="",
        )
        conference = _clean_metadata_text(
            _extract_field(
            [
                r"Conference or journal name:\**\s*(.+)",
                r"发布平台与时间.*?[：:]\s*([^\n]+)",
            ],
            answer,
            "arXiv",
            ),
            default="arXiv",
        )
        year = _extract_field([r"Publication year:\**\s*(\d{4})", r"(\d{4})"], answer, "")
        repo = _first_url(_extract_field([r"GitHub repository link:\**\s*(.+)"], answer, "")) or "未开源"
        university = _clean_metadata_text(
            _extract_field([r"Author affiliations:\**\s*(.+)"], answer, "未知"),
            default="未知",
        )
        authors = _clean_metadata_text(
            _extract_field([r"Author list:\**\s*(.+)", r"Authors?:\**\s*(.+)"], answer, "论文未明确说明"),
            default="论文未明确说明",
        )
        paper_url = _first_url(answer) or ""
        return {
            "paper_title": paper_title,
            "conference": _normalize_venue_name(conference or "arXiv"),
            "year": year or "2026",
            "repo": repo,
            "university": university or "",
            "authors": authors or "",
            "paper_url": paper_url,
            "metadata_answer": answer,
        }

    def _fallback_metadata(self, job: dict, source_info: dict[str, str], metadata: dict[str, str], log: LogFn) -> dict[str, str]:
        paper_url = source_info.get("paper_url") or metadata.get("paper_url") or ""
        title = metadata.get("paper_title") or source_info.get("source_title") or ""
        html = _fetch_html(paper_url) if paper_url else ""
        if html:
            title = title or _extract_meta_content(html, ["citation_title", "og:title"])
            authors = metadata.get("authors") or _extract_meta_content(html, ["citation_author"])
            institution = metadata.get("university") or _extract_meta_content(html, ["citation_author_institution"])
            venue = metadata.get("conference") or _extract_meta_content(
                html,
                ["citation_conference_title", "citation_journal_title"],
            )
            year = metadata.get("year") or _extract_meta_content(html, ["citation_publication_date", "citation_date"])
            repo = metadata.get("repo") or _first_url(html) or "未开源"
            metadata.update(
                {
                    "paper_title": _clean_metadata_text(title, ""),
                    "authors": _clean_metadata_text(authors, ""),
                    "university": _clean_metadata_text(institution, ""),
                    "conference": _normalize_venue_name(venue or metadata.get("conference") or "arXiv"),
                    "year": re.search(r"(20\d{2})", year or "") and re.search(r"(20\d{2})", year or "").group(1) or metadata.get("year") or "2026",
                    "repo": repo,
                    "paper_url": paper_url,
                }
            )
        input_text = str(job.get("input_text") or "")
        if not metadata.get("paper_title"):
            match = re.match(r"([A-Z][^(\n]+)", input_text)
            if match:
                metadata["paper_title"] = _clean_source_title(match.group(1))
        if not metadata.get("paper_url") and _is_url(input_text):
            metadata["paper_url"] = input_text.strip()
        if metadata.get("conference"):
            metadata["conference"] = _normalize_venue_name(metadata["conference"])
        log("metadata", f"Resolved metadata title='{metadata.get('paper_title') or '-'}' venue='{metadata.get('conference') or '-'}'", "INFO")
        return metadata

    def _validate_metadata(self, metadata: dict[str, str]) -> dict[str, str]:
        title = _clean_metadata_text(metadata.get("paper_title") or "", "")
        authors = _clean_metadata_text(metadata.get("authors") or "", "")
        institution = _clean_metadata_text(metadata.get("university") or "", "")
        venue = _normalize_venue_name(metadata.get("conference") or "arXiv")
        if title.lower() in {"untitled paper", "available in the text"}:
            title = ""
        if any(token in title.lower() for token in {"available in the text", "untitled"}):
            title = ""
        if not title:
            raise RuntimeError("metadata incomplete: missing paper title")
        if not authors or authors in {"论文未明确说明", "未知"}:
            raise RuntimeError("metadata incomplete: missing authors")
        if not institution or institution in {"论文未明确说明", "未知"}:
            raise RuntimeError("metadata incomplete: missing institution")
        if not venue:
            raise RuntimeError("metadata incomplete: missing venue")
        metadata["paper_title"] = title
        metadata["authors"] = authors
        metadata["university"] = institution
        metadata["conference"] = venue
        return metadata

    def _query_notes(self, notebook_id: str, source_id: str, log: LogFn, *, archetype: str) -> str:
        log("notes", f"Generating Chinese notes for source {source_id}", "INFO")
        archetype_requirements = {
            "systems": "重点说明系统边界、data/control plane、核心工作流、部署机制、hot-swap 或运行时反馈闭环。",
            "evaluation": "重点说明 benchmark 构造、任务定义、数据来源、指标、baseline 强度、实验有效性与 threats to validity。",
            "safety": "重点说明风险类别、攻击/失效模式、安全边界、评测协议、部署风险与防御启发。",
            "tuning": "重点说明搜索空间、反馈信号、优化循环、warm-start/收敛性、系统收益与成本权衡。",
            "retrieval": "重点说明记忆/检索架构、索引或缓存机制、上下文管理、评测协议与系统权衡。",
            "general": "重点说明问题定义、核心方法、实验设计、结果、局限性与工程含义。",
        }
        question = (
            "请基于论文内容生成一份精炼但完整的中文阅读稿，直接输出 markdown 正文，不要输出 YAML frontmatter，不要输出前言。"
            "请使用统一结构，但不要把格式写得过碎。"
            "严格采用下面的顶层结构："
            "## TL;DR"
            "3 到 5 条短 bullet，每条突出一个 paper-specific 结论。"
            "## 论文基本信息"
            "只保留 Title、Venue、Year、Authors、Paper URL 这 5 个字段；不要写 repo、university、notebook 等噪音字段。"
            "## 1. 整体概括"
            "## 2. 背景与动机"
            "## 3. 方法与系统设计"
            "## 4. 实验设置"
            "## 5. 结果与分析"
            "## 6. 总结与思考"
            "各章节可以用短段落加 bullet 混排，但不要再继续拆太多子标题。"
            "要求："
            "第一，内容要覆盖完整，不能因为格式精炼而遗漏关键方法、实验或结论；"
            "第二，不要编造论文中没有出现的信息，不确定就明确写‘论文未明确说明’;"
            "第三，保留关键英文术语，采用‘中文（English）’或直接使用英文术语的方式；"
            "第四，不要输出类似 [1]、[2] 的引用标号；"
            "第五，结果与分析必须写出具体数字、对比对象和工程意义；"
            "第六，总结与思考必须写局限性、部署风险或开放问题，不能只是重复摘要；"
            "第七，按论文原文结构理解内容，尤其要区分 background/motivation、method/system design、experimental setup、results；"
            f"第八，这篇论文的通用类型偏向 {archetype}，请遵循这个类型的常见分析重点：{archetype_requirements.get(archetype, archetype_requirements['general'])}"
        )
        result = self.runtime.run(
            [
                "nlm",
                "notebook",
                "query",
                str(notebook_id),
                "--source-ids",
                source_id,
                "--timeout",
                "240",
                "--json",
                question,
            ],
            timeout=270.0,
        )
        if not result.ok:
            raise RuntimeError((result.stderr or result.stdout).strip() or "notes query failed")
        payload = _parse_nlm_query_output(result.stdout)
        return _polish_notes_markdown(str(payload.get("answer") or ""))

    def _build_note_content(
        self,
        job: dict,
        source_info: dict[str, str],
        metadata: dict[str, str],
        notes: str,
        *,
        assets: AssetList | None = None,
        archive_topic: str = '',
    ) -> str:
        conference_slug = _slug(metadata["conference"].replace(" ", "-")) or "arXiv"
        frontmatter = (
            "---\n"
            f'title: "{metadata["paper_title"]}"\n'
            f'conference: "{metadata["conference"]}"\n'
            f"year: {metadata['year']}\n"
            f'framework_version: "{self.runtime.config.framework_version}"\n'
            f'canonical_paper_key: "{_canonical_paper_key(metadata["paper_title"])}"\n'
            f'repo: "{metadata["repo"]}"\n'
            f'institution: "{_summarize_institutions(metadata["university"])}"\n'
            f'paper_url: "{source_info["paper_url"] or metadata["paper_url"]}"\n'
            f'tags: ["paper", "{conference_slug}/{metadata["year"]}", "{_slug((archive_topic or job["notebook_title"])).replace("-", "_")}"]\n'
            f"created_date: {datetime.now(UTC).date().isoformat()}\n"
            f'notebook: "{job["notebook_title"]}"\n'
            f'archive_topic: "{archive_topic or job["notebook_title"]}"\n'
            "---\n\n"
        )
        body = notes or metadata["metadata_answer"]
        body = self._normalize_note_body(body, metadata, source_info)
        if assets:
            body = self._inject_figure_section(body, assets)
        return frontmatter + body + "\n"

    def _normalize_note_body(self, body: str, metadata: dict[str, str], source_info: dict[str, str]) -> str:
        cleaned = body.strip()
        replacements = {
            "## 📄 论文概览": "## 1. 整体概括",
            "## 💡 核心直觉": "## 2. 背景与动机",
            "## 🎯 研究问题与动机": "## 2. 背景与动机",
            "## ✨ 主要贡献": "## 3. 方法与系统设计",
            "## 🔬 基准/方法/系统设计": "## 3. 方法与系统设计",
            "## 🧪 实验设置与评测协议": "## 4. 实验设置",
            "## 📈 关键结果与分析": "## 5. 结果与分析",
            "## 🔍 批判性评估": "## 6. 总结与思考",
            "## ⚠️ 局限性与风险": "## 6. 总结与思考",
            "## 🚀 实践启发与未来工作": "## 6. 总结与思考",
            "## 📚 术语表": "## 6. 总结与思考",
        }
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        info_block = (
            "## 论文基本信息\n"
            f"- Title: {metadata['paper_title']}\n"
            f"- Venue: {metadata['conference']}\n"
            f"- Year: {metadata['year']}\n"
            f"- Authors: {metadata.get('authors') or '论文未明确说明'}\n"
            f"- Institution: {_summarize_institutions(metadata.get('university') or '')}\n"
            f"- Paper URL: {source_info['paper_url'] or metadata['paper_url'] or '论文未明确说明'}\n"
            f"- Framework Version: {self.runtime.config.framework_version}\n"
        )
        if "## 论文基本信息" not in cleaned:
            cleaned = info_block + "\n\n" + cleaned
        if "## TL;DR" not in cleaned:
            bullets = re.findall(r"^\s*[*-]\s+(.+)", cleaned, flags=re.M)
            tldr_lines = bullets[:4]
            if not tldr_lines:
                sentences = [line.strip() for line in cleaned.splitlines() if line.strip()][:4]
                tldr_lines = sentences[:4]
            tldr = "## TL;DR\n" + "\n".join(f"- {line}" for line in tldr_lines if line) + "\n\n"
            cleaned = tldr + cleaned
        return _normalize_heading_spacing(cleaned)

    def _inject_figure_section(self, body: str, assets: AssetList) -> str:
        lines = body.splitlines()
        insertions: dict[int, list[str]] = {}
        heading_map = {
            'summary': '## 1. 整体概括',
            'background': '## 2. 背景与动机',
            'method': '## 3. 方法与系统设计',
            'experiment': '## 4. 实验设置',
            'results': '## 5. 结果与分析',
            'conclusion': '## 6. 总结与思考',
        }
        fallback_order = ['background', 'method', 'experiment', 'results']

        for idx, asset in enumerate(assets, start=1):
            section_key = asset.get('placement_target') or asset.get('section_key') or fallback_order[min(idx - 1, len(fallback_order) - 1)]
            heading_prefix = heading_map.get(section_key, '## 🔬')
            caption = asset.get("caption") or f"Figure {idx}"
            block = [
                '',
                "<figure class=\"paper-figure\">",
                f'  <img src="{asset["markdown_path"]}" alt="{caption}">',
                f'  <figcaption>{caption}</figcaption>',
                "</figure>",
            ]
            insert_at = None
            for line_index, line in enumerate(lines):
                if line.startswith(heading_prefix):
                    insert_at = line_index + 1
                    break
            if insert_at is None:
                insert_at = len(lines)
            insertions.setdefault(insert_at, []).extend(block)

        output: list[str] = []
        for idx, line in enumerate(lines):
            output.append(line)
            if idx + 1 in insertions:
                output.extend(insertions[idx + 1])
        if len(lines) in insertions:
            output.extend(insertions[len(lines)])
        return "\n".join(output).strip() + "\n"

    def _resolve_archive_topic(
        self,
        job: dict,
        metadata: dict[str, str],
        notes: str,
        log: LogFn,
    ) -> str:
        taxonomy_note = self.runtime.config.obsidian_notes_root / 'Paper Routing Taxonomy.md'
        taxonomy_topics = _load_taxonomy_topics(taxonomy_note)
        subject_text = ' '.join(
            part for part in [
                str(job.get('input_text') or ''),
                str(metadata.get('paper_title') or ''),
                str(job.get('paper_title') or ''),
                str(job.get('notebook_title') or ''),
                notes[:1200],
            ] if part
        )
        suggested, overlap = _suggest_topic_notebook(subject_text)
        if suggested not in taxonomy_topics:
            suggested = next((topic for topic in taxonomy_topics if topic == suggested), taxonomy_topics[0])
        detail = ', '.join(overlap[:5]) if overlap else 'default topic'
        log('routing', f"Mapped note storage to taxonomy topic '{suggested}' ({detail})", 'INFO')
        return suggested

    def _resolve_output_target(self, job: dict, metadata: dict[str, str], archive_topic: str) -> OutputPlan:
        repo = self.runtime.config.obsidian_sync_repo
        notes_root = repo / self.runtime.config.obsidian_sync_subdir / archive_topic
        notes_root.mkdir(parents=True, exist_ok=True)
        conference_slug = _slug(metadata["conference"].replace(" ", "-")) or "arXiv"
        title_slug = _short_title_slug(metadata["paper_title"])
        base_name = f"{metadata['year']}-{conference_slug}-{title_slug}"
        target = notes_root / f"{base_name}.md"
        version = 2
        while target.exists():
            target = notes_root / f"{base_name}-v{version}.md"
            version += 1
        relative_output = target.relative_to(repo)
        assets_dir = repo / self.runtime.config.obsidian_sync_subdir / "_assets" / archive_topic / target.stem
        relative_assets_dir = assets_dir.relative_to(repo)
        return OutputPlan(
            target=target,
            relative_output=relative_output,
            assets_dir=assets_dir,
            relative_assets_dir=relative_assets_dir,
            taxonomy_topic=archive_topic,
        )

    def _extract_figures(
        self,
        job: dict,
        source_info: dict[str, str],
        output_plan: OutputPlan,
        log: LogFn,
    ) -> AssetList:
        paper_url = source_info.get("paper_url") or ""
        artifact_dir = Path(str(job.get("artifact_dir") or self.runtime.config.artifacts_dir / str(job.get("id") or "unknown")))
        artifact_dir.mkdir(parents=True, exist_ok=True)

        source_url = self._source_archive_url(paper_url)
        if source_url:
            source_path = artifact_dir / "paper-source.tar"
            try:
                self._download_binary(source_url, source_path)
                assets = self._extract_figures_from_source_archive(source_path, output_plan)
                if assets:
                    log("figures", f"Extracted {len(assets)} figure candidates from source archive into {output_plan.relative_assets_dir.as_posix()}", "INFO")
                    return assets
                log("figures", "No suitable figures found in source archive; falling back to PDF", "INFO")
            except Exception as exc:
                log("figures", f"Source archive extraction failed: {exc}", "WARN")

        pdf_url = self._pdf_candidate_url(paper_url)
        if not pdf_url:
            log("figures", "No downloadable PDF URL detected; skipping figure extraction", "INFO")
            return []
        pdf_path = artifact_dir / "paper.pdf"
        try:
            self._download_binary(pdf_url, pdf_path)
        except Exception as exc:
            log("figures", f"PDF download failed: {exc}", "WARN")
            return []
        try:
            assets = self._extract_figures_from_pdf(pdf_path, output_plan)
        except Exception as exc:
            log("figures", f"Figure extraction failed: {exc}", "WARN")
            return []
        if assets:
            log("figures", f"Extracted {len(assets)} figure candidates from PDF into {output_plan.relative_assets_dir.as_posix()}", "INFO")
        else:
            log("figures", "No suitable figure candidates found in PDF", "INFO")
        return assets

    def _source_archive_url(self, paper_url: str) -> str:
        if not paper_url:
            return ""
        parsed = urlparse(paper_url)
        if 'arxiv.org' in parsed.netloc and parsed.path.startswith('/abs/'):
            return f"https://arxiv.org/e-print/{parsed.path.split('/abs/', 1)[1]}"
        return ""

    def _pdf_candidate_url(self, paper_url: str) -> str:
        if not paper_url:
            return ""
        if paper_url.endswith('.pdf'):
            return paper_url
        parsed = urlparse(paper_url)
        if 'arxiv.org' in parsed.netloc and parsed.path.startswith('/abs/'):
            return f"https://arxiv.org/pdf/{parsed.path.split('/abs/', 1)[1]}.pdf"
        return ""

    def _download_binary(self, url: str, target: Path) -> None:
        request = Request(url, headers={"User-Agent": "paper-queue/1.0"})
        with urlopen(request, timeout=60) as response:
            data = response.read()
        target.write_bytes(data)

    def _extract_figures_from_source_archive(self, archive_path: Path, output_plan: OutputPlan) -> AssetList:
        extract_root = archive_path.parent / "source"
        if extract_root.exists():
            for child in sorted(extract_root.glob('*'), reverse=True):
                if child.is_dir():
                    import shutil
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, mode="r:*") as tar:
            tar.extractall(extract_root)
        figure_records = self._parse_tex_figure_refs(extract_root)
        candidate_paths = self._source_image_candidates(extract_root, figure_records)
        output_plan.assets_dir.mkdir(parents=True, exist_ok=True)
        assets: AssetList = []
        for candidate, figure_record in candidate_paths:
            asset = self._export_source_figure(candidate, output_plan, len(assets) + 1, figure_record=figure_record)
            if asset:
                assets.append(asset)
            if len(assets) >= 6:
                break
        return assets

    def _parse_tex_figure_refs(self, root: Path) -> list[dict[str, str | list[str]]]:
        figure_records: list[dict[str, str | list[str]]] = []
        token_pattern = re.compile(
            r"\\section\*?\{[^}]+\}|\\subsection\*?\{[^}]+\}|\\subsubsection\*?\{[^}]+\}|\\begin\{figure\*?\}.*?\\end\{figure\*?\}",
            flags=re.S,
        )
        section_pattern = re.compile(r"\\section\*?\{([^}]+)\}")
        subsection_pattern = re.compile(r"\\subsection\*?\{([^}]+)\}")
        subsubsection_pattern = re.compile(r"\\subsubsection\*?\{([^}]+)\}")
        include_pattern = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
        caption_pattern = re.compile(r"\\caption\{([^}]*)\}", flags=re.S)
        tex_files = sorted(root.rglob('*.tex'))
        for tex_path in tex_files:
            try:
                content = tex_path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            current_section = ""
            current_subsection = ""
            for token in token_pattern.finditer(content):
                chunk = token.group(0)
                section_match = section_pattern.match(chunk)
                if section_match:
                    current_section = re.sub(r"\s+", " ", section_match.group(1)).strip()
                    current_subsection = ""
                    continue
                subsection_match = subsection_pattern.match(chunk)
                if subsection_match:
                    current_subsection = re.sub(r"\s+", " ", subsection_match.group(1)).strip()
                    continue
                subsubsection_match = subsubsection_pattern.match(chunk)
                if subsubsection_match:
                    current_subsection = re.sub(r"\s+", " ", subsubsection_match.group(1)).strip()
                    continue
                refs = []
                for ref in include_pattern.findall(chunk):
                    value = ref.strip().split(",")[-1].strip()
                    if value and value not in refs:
                        refs.append(value)
                if not refs:
                    continue
                caption_match = caption_pattern.search(chunk)
                caption = ""
                if caption_match:
                    caption = re.sub(r"\\textbf\{([^}]*)\}", r"\1", caption_match.group(1))
                    caption = re.sub(r"\\underline\{([^}]*)\}", r"\1", caption)
                    caption = re.sub(r"\\[A-Za-z]+\s*", "", caption)
                    caption = re.sub(r"[{}]+", "", caption)
                    caption = re.sub(r"\s+", " ", caption).strip()
                figure_records.append(
                    {
                        "refs": refs,
                        "section": current_section,
                        "subsection": current_subsection,
                        "caption": caption,
                    }
                )
        return figure_records

    def _source_image_candidates(self, root: Path, figure_records: list[dict[str, str | list[str]]]) -> list[tuple[Path, dict[str, str | list[str]]]]:
        files = [p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.pdf'}]
        by_stem: dict[str, list[Path]] = {}
        for file_path in files:
            by_stem.setdefault(file_path.stem.lower(), []).append(file_path)
        ordered: list[tuple[Path, dict[str, str | list[str]]]] = []
        seen: set[Path] = set()
        for record in figure_records:
            refs = record.get("refs") or []
            for ref in refs:
                ref_path = Path(str(ref))
                ref_stem = ref_path.stem.lower()
                for candidate in by_stem.get(ref_stem, []):
                    if candidate not in seen:
                        ordered.append((candidate, record))
                        seen.add(candidate)
        remaining = sorted((p for p in files if p not in seen), key=lambda p: p.stat().st_size, reverse=True)
        ordered.extend((p, {}) for p in remaining)
        return ordered

    def _export_source_figure(
        self,
        source_path: Path,
        output_plan: OutputPlan,
        index: int,
        figure_record: dict[str, str | list[str]] | None = None,
    ) -> dict[str, str] | None:
        suffix = source_path.suffix.lower()
        if suffix == '.pdf':
            doc = fitz.open(source_path)
            try:
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                asset_path = output_plan.assets_dir / f"figure-{index:02d}.png"
                pix.save(asset_path)
            finally:
                doc.close()
        else:
            asset_path = output_plan.assets_dir / f"figure-{index:02d}{suffix}"
            asset_path.write_bytes(source_path.read_bytes())
        markdown_path = Path("..") / "_assets" / output_plan.taxonomy_topic / output_plan.target.stem / asset_path.name
        figure_record = figure_record or {}
        caption = str(figure_record.get("caption") or "").strip()
        paper_section = str(figure_record.get("section") or "").strip()
        paper_subsection = str(figure_record.get("subsection") or "").strip()
        placement_target = self._classify_figure_section(
            " ".join(part for part in [source_path.name, caption, paper_section, paper_subsection] if part)
        )
        return {
            'page': f"source:{source_path.name}",
            'markdown_path': markdown_path.as_posix(),
            'source_name': source_path.name,
            'caption': caption,
            'paper_section': paper_section,
            'paper_subsection': paper_subsection,
            'placement_target': placement_target,
            'section_key': placement_target,
        }

    def _classify_figure_section(self, label: str, fallback_index: int = 0) -> str:
        lowered = label.lower()
        if any(token in lowered for token in ['overview', 'funnel', 'pipeline', 'architecture', 'framework', 'workflow', 'implementation', 'execution model', 'system overview', 'program synthesis']):
            return 'method'
        if any(token in lowered for token in ['setup', 'cluster', 'environment', 'serving policy deep dive']):
            return 'experiment'
        if any(token in lowered for token in ['benchmark', 'task', 'result', 'performance', 'compare', 'level', 'vertical', 'evaluation', 'convergence', 'warm start', 'e2e', 'end-to-end']):
            return 'results'
        if any(token in lowered for token in ['motivation', 'background', 'problem', 'trade-off', 'tradeoff', 'introduction']):
            return 'background'
        if any(token in lowered for token in ['limitation', 'threat', 'risk', 'ablation', 'error']):
            return 'conclusion'
        if fallback_index == 0:
            return 'method'
        if fallback_index == 1:
            return 'results'
        if fallback_index == 2:
            return 'experiment'
        return 'background'

    def _extract_figures_from_pdf(self, pdf_path: Path, output_plan: OutputPlan) -> AssetList:
        output_plan.assets_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        candidates: list[tuple[int, int, bytes]] = []
        try:
            for page_index in range(min(len(doc), 12)):
                page = doc.load_page(page_index)
                for image_info in page.get_images(full=True):
                    xref = image_info[0]
                    base = doc.extract_image(xref)
                    image_bytes = base.get('image', b'')
                    width = int(base.get('width', 0) or 0)
                    height = int(base.get('height', 0) or 0)
                    if width < 240 or height < 180:
                        continue
                    area = width * height
                    candidates.append((area, page_index + 1, image_bytes))
        finally:
            doc.close()
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: AssetList = []
        seen_sizes: set[tuple[int, int]] = set()
        for index, (area, page_no, image_bytes) in enumerate(candidates[:12], start=1):
            signature = (page_no, len(image_bytes))
            if signature in seen_sizes:
                continue
            seen_sizes.add(signature)
            asset_path = output_plan.assets_dir / f"figure-{len(selected)+1:02d}.png"
            asset_path.write_bytes(image_bytes)
            markdown_path = Path("..") / "_assets" / output_plan.taxonomy_topic / output_plan.target.stem / asset_path.name
            selected.append({
                'page': str(page_no),
                'markdown_path': markdown_path.as_posix(),
                'source_name': f'page-{page_no}',
                'caption': '',
                'paper_section': '',
                'paper_subsection': '',
                'placement_target': self._classify_figure_section(f'page-{page_no}', fallback_index=len(selected)),
                'section_key': self._classify_figure_section(f'page-{page_no}', fallback_index=len(selected)),
            })
            if len(selected) >= 6:
                break
        return selected

    def _sync_repo(self, log: LogFn, *, attempt: int) -> None:
        repo = self.runtime.config.obsidian_sync_repo
        branch = self.runtime.config.obsidian_sync_branch
        if not (repo / ".git").exists():
            raise RuntimeError(f"git repo missing: {repo}")
        log("git_prepare", f"Syncing {repo} to origin/{branch} (attempt {attempt})", "INFO")
        fetch_result = self.runtime.run(
            [
                "git",
                "-C",
                str(repo),
                "fetch",
                "origin",
                f"refs/heads/{branch}:refs/remotes/origin/{branch}",
            ],
            timeout=120.0,
        )
        if not fetch_result.ok:
            raise RuntimeError((fetch_result.stderr or fetch_result.stdout).strip() or "git fetch failed")
        checkout_result = self.runtime.run(
            ["git", "-C", str(repo), "checkout", "-B", branch, f"origin/{branch}"],
            timeout=60.0,
        )
        if not checkout_result.ok:
            raise RuntimeError((checkout_result.stderr or checkout_result.stdout).strip() or "git checkout failed")
        reset_result = self.runtime.run(
            ["git", "-C", str(repo), "reset", "--hard", f"origin/{branch}"],
            timeout=60.0,
        )
        if not reset_result.ok:
            raise RuntimeError((reset_result.stderr or reset_result.stdout).strip() or "git reset failed")
        clean_result = self.runtime.run(
            ["git", "-C", str(repo), "clean", "-fd"],
            timeout=60.0,
        )
        if not clean_result.ok:
            raise RuntimeError((clean_result.stderr or clean_result.stdout).strip() or "git clean failed")
        log("git_sync", f"Repository synced to origin/{branch}", "INFO")

    def _write_note_to_repo(
        self,
        output_plan: OutputPlan,
        note_content: str,
        log: LogFn,
    ) -> Path:
        output_plan.target.parent.mkdir(parents=True, exist_ok=True)
        output_plan.target.write_text(note_content, encoding="utf-8")
        log("write", f"Wrote markdown to {output_plan.relative_output.as_posix()}", "INFO")
        return output_plan.relative_output

    def _commit_note(self, relative_output: Path, commit_message: str, log: LogFn) -> str:
        repo = self.runtime.config.obsidian_sync_repo
        add_targets = [relative_output.as_posix()]
        asset_dir = repo / self.runtime.config.obsidian_sync_subdir / "_assets" / relative_output.parent.name / relative_output.stem
        if asset_dir.exists():
            add_targets.append(asset_dir.relative_to(repo).as_posix())
        add_result = self.runtime.run(
            ["git", "-C", str(repo), "add", "--", *add_targets],
            timeout=60.0,
        )
        if not add_result.ok:
            raise RuntimeError((add_result.stderr or add_result.stdout).strip() or "git add failed")
        commit_result = self.runtime.run(
            ["git", "-C", str(repo), "commit", "-m", commit_message],
            timeout=60.0,
        )
        if commit_result.ok:
            log("git_commit", commit_message, "INFO")
            return "committed"
        message = (commit_result.stderr or commit_result.stdout).strip()
        if "nothing to commit" in message.lower():
            log("git_commit", "Nothing to commit after write", "INFO")
            return "noop"
        raise RuntimeError(message or "git commit failed")
