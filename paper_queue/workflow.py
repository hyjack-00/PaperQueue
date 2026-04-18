from __future__ import annotations

import hashlib
import json
from html import unescape
import io
import re
import shlex
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


def _embedded_source_url(value: str) -> str:
    text = value.strip()
    direct = _first_url(text)
    if direct:
        return direct
    arxiv_match = re.search(r"\barxiv:(\d{4}\.\d{4,5})(?:v\d+)?\b", text, flags=re.I)
    if arxiv_match:
        return f"https://arxiv.org/abs/{arxiv_match.group(1)}"
    openreview_match = re.search(r"\bopenreview\.net/forum\?id=([A-Za-z0-9_-]+)\b", text)
    if openreview_match:
        return f"https://openreview.net/forum?id={openreview_match.group(1)}"
    return ""


def _title_like_input(value: str) -> str:
    text = value.strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\((?:arXiv|ICLR|NeurIPS|ICML|ISCA|OSDI|SOSP|ASPLOS)[^)]*\)", "", text, flags=re.I).strip()
    text = re.sub(r"\[[^\]]+\]", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip(" -:")
    return text


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


def _topic_dir_slug(topic: str) -> str:
    return _slug(topic.replace("/", "-")) or "uncategorized"


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


def _strip_tex_commands(value: str) -> str:
    cleaned = re.sub(r"\\(?:textbf|textit|mathrm|mathbf|underline|emph)\{([^}]*)\}", r"\1", value)
    cleaned = re.sub(r"\\(?:thanks|footnote|email|href)\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", cleaned)
    cleaned = cleaned.replace("{", " ").replace("}", " ")
    cleaned = cleaned.replace("\\\\", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ,;")


def _looks_like_institution(value: str) -> bool:
    lowered = value.lower()
    tokens = (
        "university", "institute", "lab", "laboratory", "school", "college", "academy",
        "research", "department", "center", "centre", "meta", "google", "microsoft",
        "nvidia", "openai", "anthropic", "amazon", "apple", "bytedance", "alibaba",
        "tencent", "mit", "cmu", "stanford", "berkeley", "tsinghua", "pku",
    )
    return any(token in lowered for token in tokens)


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


def _normalize_length_label(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"short", "medium", "long"}:
        return lowered
    return "medium"


def _figure_alt_text(asset: dict[str, str], index: int) -> str:
    caption = _clean_figure_caption(asset.get("caption") or "")
    if caption:
        return caption[:180]
    subsection = str(asset.get("paper_subsection") or "").strip()
    section = str(asset.get("paper_section") or "").strip()
    if subsection:
        return subsection[:180]
    if section:
        return section[:180]
    return f"Figure {index}"


def _figure_caption_text(asset: dict[str, str], index: int) -> str:
    source_name = str(asset.get("source_name") or "").lower()
    if "execution_model" in source_name:
        return "Execution model: trace snapshot generation, evaluator replay, and policy deployment cycle"
    caption = _clean_figure_caption(asset.get("caption") or "")
    if caption:
        return _compress_figure_caption(caption)
    fallback = _figure_alt_text(asset, index)
    if fallback.lower().startswith("figure "):
        return ""
    return fallback


def _clean_figure_caption(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = re.sub(r"\\ref\{[^}]*\}", "", text)
    text = re.sub(r"\\subref\{[^}]*\}", "", text)
    text = re.sub(r"\\cite[t|p]?\{[^}]*\}", "", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?", "", text)
    text = text.replace("~", " ")
    text = text.replace("'s two-plane", "the two-plane")
    text = re.sub(r"\(subsec:[^)]+$", "", text)
    text = re.sub(r"\((?:left|right)\s*$", "", text, flags=re.I)
    text = re.sub(r"\b(?:left|right):\s*$", "", text, flags=re.I)
    text = re.sub(r"\s+\d+$", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;:.")
    if text.lower() in {"left", "right", "figure", "overview"}:
        return ""
    if len(text) < 12:
        return ""
    return text


def _compress_figure_caption(text: str) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(parts) >= 2 and len(parts[-1].split()) <= 4:
        parts = parts[:-1]
    compact = " ".join(parts) if parts else text
    words = compact.split()
    if len(words) > 28 and parts:
        compact = parts[0]
        words = compact.split()
    if len(words) > 28:
        compact = " ".join(words[:28]).rstrip(",;:.") + "..."
    return compact.strip()


@dataclass(slots=True)
class PaperResult:
    status: str
    paper_title: str
    canonical_paper_key: str
    source_fingerprint: str
    framework_version: str
    output_path: str
    review_pdf_path: str
    review_text_path: str
    review_summary: str
    summary: str
    error: str


@dataclass(slots=True)
class OutputPlan:
    target: Path
    relative_output: Path
    assets_dir: Path
    relative_assets_dir: Path
    taxonomy_topic: str
    taxonomy_topic_dir: str


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
        structure = self._query_structure_analysis(job["notebook_id"], source_info["source_id"], log, archetype=archetype)
        notes = self._query_notes(
            job["notebook_id"],
            source_info["source_id"],
            log,
            archetype=structure.get("archetype") or archetype,
            section_guidance=self._section_guidance_text(structure),
        )
        last_error = "git push failed"
        for attempt in range(1, 4):
            self._sync_repo(log, attempt=attempt)
            archive_topic = self._resolve_archive_topic(job, metadata, notes, log)
            taxonomy_note = self.runtime.config.obsidian_notes_root / 'Paper Routing Taxonomy.md'
            taxonomy_topics = _load_taxonomy_topics(taxonomy_note)
            preflight = self._agent_notes_preflight(metadata, notes, taxonomy_topics, log)
            if preflight:
                fourth_title = preflight["fourth_title"]
                if fourth_title and fourth_title != metadata.get("paper_title"):
                    log("preflight", f"Updating paper_title from '{metadata.get('paper_title')}' to '{fourth_title}'", "INFO")
                    metadata["paper_title"] = fourth_title
                suggested_topic = preflight.get("topic_folder", "")
                if suggested_topic in taxonomy_topics:
                    archive_topic = suggested_topic
                    log("preflight", f"Agent selected topic folder: {archive_topic}", "INFO")
            output_plan = self._resolve_output_target(job, metadata, archive_topic, preflight=preflight)
            assets = self._extract_figures(job, source_info, output_plan, log)
            note_content = self._build_note_content(job, source_info, metadata, notes, assets=assets, archive_topic=archive_topic, log=log)
            relative_output = self._write_note_to_repo(output_plan, note_content, log)
            commit_message = f"Add paper note: {metadata['paper_title'] or relative_output.stem}"
            commit_result = self._commit_note(relative_output, commit_message, log)
            if commit_result == "noop":
                review_pdf_path = self._export_review_pdf(job, output_plan, log)
                review_text_path, review_summary = self._review_readability(job, output_plan, review_pdf_path, log)
                return PaperResult(
                    status="completed",
                    paper_title=metadata["paper_title"],
                    canonical_paper_key=_canonical_paper_key(metadata["paper_title"]),
                    source_fingerprint=fingerprint,
                    framework_version=self.runtime.config.framework_version,
                    output_path=relative_output.as_posix(),
                    review_pdf_path=review_pdf_path,
                    review_text_path=review_text_path,
                    review_summary=review_summary,
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
                review_pdf_path = self._export_review_pdf(job, output_plan, log)
                review_text_path, review_summary = self._review_readability(job, output_plan, review_pdf_path, log)
                return PaperResult(
                    status="completed",
                    paper_title=metadata["paper_title"],
                    canonical_paper_key=_canonical_paper_key(metadata["paper_title"]),
                    source_fingerprint=fingerprint,
                    framework_version=self.runtime.config.framework_version,
                    output_path=relative_output.as_posix(),
                    review_pdf_path=review_pdf_path,
                    review_text_path=review_text_path,
                    review_summary=review_summary,
                    summary=notes.splitlines()[0][:240] if notes else metadata["paper_title"],
                    error="",
                )
            last_error = (push_result.stderr or push_result.stdout).strip() or "git push failed"
            log("git_push", f"Push attempt {attempt} failed: {last_error}", "WARN")
            if attempt >= 3:
                break
        raise RuntimeError(last_error)

    def _agent_route(
        self,
        paper_description: str,
        notebooks: list[dict[str, str]],
        log: LogFn,
    ) -> dict | None:
        if self.runtime.config.agent_backend != "claude-glm":
            return None

        notebook_list_str = "\n".join(
            f"- ID: {nb['id']}, Title: {nb['title']}"
            for nb in notebooks
            if str(nb.get("title") or "").strip()
        )
        topic_list_str = "\n".join(
            f"- {name}" for name, _ in ROUTE_TOPIC_MAP
        )

        prompt = self.runtime.prompt_loader.load(
            self.runtime.config.routing_prompt_file,
            notebook_list=notebook_list_str or "(empty)",
            topic_list=topic_list_str,
            paper_description=paper_description,
        )

        command_parts = shlex.split(self.runtime.config.claude_glm_command)
        env: dict[str, str] = {}
        while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
            key, value = command_parts.pop(0).split("=", 1)
            env[key] = value
        if not command_parts:
            log("routing", "Agent routing skipped: empty agent command", "WARN")
            return None

        result = self.runtime.run(
            [
                *command_parts,
                "-p",
                "--output-format",
                "text",
                prompt,
            ],
            env=env,
            cwd=self.runtime.config.base_dir,
            timeout=min(self.runtime.config.agent_timeout_seconds, 60.0),
        )
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "agent routing failed"
            log("routing", f"Agent routing failed: {message}", "WARN")
            return None

        output = (result.stdout or "").strip()
        if not output:
            log("routing", "Agent routing returned empty output", "WARN")
            return None

        json_match = re.search(r"\{[^{}]*\}", output, re.S)
        if not json_match:
            log("routing", f"Agent routing returned non-JSON: {output[:200]}", "WARN")
            return None

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            log("routing", f"Agent routing returned invalid JSON: {json_match.group()[:200]}", "WARN")
            return None

        action = parsed.get("action")
        if action not in ("reuse", "create"):
            log("routing", f"Agent routing returned invalid action: {action}", "WARN")
            return None

        log("routing", f"Agent routing result: action={action}, title={parsed.get('second_title', '?')}", "INFO")
        return parsed

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
        source_url = _embedded_source_url(subject_text)
        if source_url:
            extracted_title = _fetch_arxiv_title(source_url) or _title_like_input(subject_text)
            if extracted_title:
                subject_text = extracted_title
                if set_paper_title:
                    set_paper_title(extracted_title)
                log("routing", f"Resolved routing title: {extracted_title}", "INFO")
        elif not _is_url(subject_text):
            normalized_title = _title_like_input(subject_text)
            if normalized_title:
                subject_text = normalized_title

        notebooks, error = self.runtime.notebook_list()
        if error:
            raise RuntimeError(error)

        candidates = [item for item in notebooks if str(item.get("title") or "").strip()]

        # Agent routing (primary path)
        agent_result = self._agent_route(subject_text, candidates, log)
        if agent_result:
            second_title = str(agent_result.get("second_title") or "").strip()
            if second_title and set_paper_title:
                set_paper_title(second_title)
                log("routing", f"Agent extracted second title: {second_title}", "INFO")

            action = agent_result.get("action")
            if action == "reuse":
                target_id = str(agent_result.get("notebook_id") or "").strip()
                matched = next((nb for nb in candidates if nb["id"] == target_id), None)
                if matched:
                    job["notebook_id"] = matched["id"]
                    job["notebook_title"] = matched["title"]
                    if set_notebook:
                        set_notebook(matched["id"], matched["title"])
                    log("routing", f"Agent reused notebook '{matched['title']}'", "INFO")
                    return
                log("routing", f"Agent reuse notebook_id '{target_id}' not found, falling back", "WARN")

            elif action == "create":
                topic_name = str(agent_result.get("topic") or "").strip()
                if not topic_name:
                    topic_name = _suggest_topic_notebook(subject_text)[0]
                existing = next((nb for nb in candidates if nb["title"] == topic_name), None)
                if existing:
                    job["notebook_id"] = existing["id"]
                    job["notebook_title"] = existing["title"]
                    if set_notebook:
                        set_notebook(existing["id"], existing["title"])
                    log("routing", f"Agent routed to existing topic notebook '{existing['title']}'", "INFO")
                    return
                created, create_error = self.runtime.create_notebook(topic_name)
                if create_error or not created:
                    log("routing", f"Agent create notebook failed: {create_error}, falling back", "WARN")
                else:
                    job["notebook_id"] = created["id"]
                    job["notebook_title"] = created["title"]
                    if set_notebook:
                        set_notebook(created["id"], created["title"])
                    log("routing", f"Agent created notebook '{created['title']}'", "INFO")
                    return

        # Keyword routing (fallback path)
        log("routing", "Falling back to keyword-based routing", "INFO")
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

        created, create_err = self.runtime.create_notebook(new_title)
        if create_err or not created:
            raise RuntimeError(create_err or "failed to create notebook")
        job["notebook_id"] = created["id"]
        job["notebook_title"] = created["title"]
        if set_notebook:
            set_notebook(created["id"], created["title"])
        detail = ", ".join(overlap[:5]) if overlap else "default topic"
        log("routing", f"Created notebook '{created['title']}' from topic hints: {detail}", "INFO")

    def _ensure_source(self, job: dict, log: LogFn) -> dict[str, str]:
        input_text = str(job["input_text"]).strip()
        source_url_hint = _embedded_source_url(input_text)
        before = self._source_list(job["notebook_id"])
        before_ids = {item["id"] for item in before}
        if source_url_hint:
            url = source_url_hint
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

        query_text = _title_like_input(input_text) or input_text
        log("research", f"Starting research import for query: {query_text}", "INFO")
        result = self.runtime.run(
            [
                "nlm",
                "research",
                "start",
                query_text,
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

    def _agent_extract_metadata(self, nlm_answer: str, log: LogFn) -> dict | None:
        if self.runtime.config.agent_backend != "claude-glm":
            return None

        prompt = self.runtime.prompt_loader.load(
            self.runtime.config.metadata_agent_prompt_file,
            nlm_answer=nlm_answer[:15000],
        )
        command_parts = shlex.split(self.runtime.config.claude_glm_command)
        env: dict[str, str] = {}
        while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
            key, value = command_parts.pop(0).split("=", 1)
            env[key] = value
        if not command_parts:
            return None

        result = self.runtime.run(
            [*command_parts, "-p", "--output-format", "text", prompt],
            env=env,
            cwd=self.runtime.config.base_dir,
            timeout=min(self.runtime.config.agent_timeout_seconds, 60.0),
        )
        if not result.ok:
            log("metadata", "Agent metadata extraction failed, using regex fallback", "WARN")
            return None

        output = (result.stdout or "").strip()
        json_match = re.search(r"\{[^{}]*\}", output, re.S)
        if not json_match:
            log("metadata", "Agent metadata returned non-JSON, using regex fallback", "WARN")
            return None

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            log("metadata", "Agent metadata returned invalid JSON, using regex fallback", "WARN")
            return None

        log("metadata", f"Agent extracted metadata: title={parsed.get('third_title', '?')}, confidence={parsed.get('confidence', '?')}", "INFO")
        return parsed

    def _query_metadata(self, notebook_id: str, source_id: str, log: LogFn) -> dict[str, str]:
        log("metadata", f"Querying metadata for source {source_id}", "INFO")
        question = self.runtime.prompt_loader.load(self.runtime.config.metadata_prompt_file)
        payload = self._query_nlm_answer(
            notebook_id,
            source_id,
            question,
            command_timeout=180,
            process_timeout=210.0,
            error_message="metadata query failed",
        )
        answer = str(payload.get("answer") or "")

        # Agent extraction (primary path)
        agent_meta = self._agent_extract_metadata(answer, log)
        if agent_meta:
            third_title = str(agent_meta.get("third_title") or "").strip()
            authors_val = str(agent_meta.get("authors") or "").strip()
            institution_val = str(agent_meta.get("institution") or "").strip()
            venue_val = str(agent_meta.get("venue") or "").strip()
            year_val = str(agent_meta.get("year") or "").strip()
            paper_url_val = str(agent_meta.get("paper_url") or "").strip()
            repo_val = str(agent_meta.get("repo") or "").strip()
            if third_title:
                log("metadata", f"Agent confirmed third title: {third_title}", "INFO")
                return {
                    "paper_title": _clean_metadata_text(third_title, ""),
                    "conference": _normalize_venue_name(venue_val or "arXiv"),
                    "year": _extract_field([r"(20\d{2})"], year_val, "2026") or "2026",
                    "repo": _first_url(repo_val) or "未开源",
                    "university": institution_val or "",
                    "authors": authors_val or "",
                    "paper_url": _first_url(paper_url_val) or "",
                    "metadata_answer": answer,
                }

        # Regex extraction (fallback path)
        log("metadata", "Using regex-based metadata extraction", "INFO")
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
        if (
            paper_url
            and "arxiv.org" in paper_url
            and (
                not metadata.get("authors")
                or not metadata.get("university")
                or not metadata.get("paper_title")
            )
        ):
            archive_meta = self._source_archive_metadata(job, paper_url, log)
            if archive_meta:
                metadata["paper_title"] = metadata.get("paper_title") or archive_meta.get("paper_title", "")
                metadata["authors"] = metadata.get("authors") or archive_meta.get("authors", "")
                metadata["university"] = metadata.get("university") or archive_meta.get("university", "")
        if not metadata.get("university"):
            pdf_meta = self._pdf_frontmatter_metadata(job, paper_url, log)
            if pdf_meta:
                metadata["paper_title"] = metadata.get("paper_title") or pdf_meta.get("paper_title", "")
                metadata["authors"] = metadata.get("authors") or pdf_meta.get("authors", "")
                metadata["university"] = metadata.get("university") or pdf_meta.get("university", "")
        if metadata.get("conference"):
            metadata["conference"] = _normalize_venue_name(metadata["conference"])
        log("metadata", f"Resolved metadata title='{metadata.get('paper_title') or '-'}' venue='{metadata.get('conference') or '-'}'", "INFO")
        return metadata

    def _source_archive_metadata(self, job: dict, paper_url: str, log: LogFn) -> dict[str, str]:
        source_url = self._source_archive_url(paper_url)
        if not source_url:
            return {}
        artifact_dir = Path(str(job.get("artifact_dir") or self.runtime.config.artifacts_dir / str(job.get("id") or "unknown")))
        archive_path = artifact_dir / "metadata-source.tar"
        extract_root = artifact_dir / "metadata-source"
        try:
            self._download_binary(source_url, archive_path)
            if extract_root.exists():
                import shutil
                shutil.rmtree(extract_root, ignore_errors=True)
            extract_root.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, mode="r:*") as tar:
                tar.extractall(extract_root)
            parsed = self._parse_tex_metadata(extract_root)
            if parsed:
                log(
                    "metadata",
                    f"Recovered metadata from source archive: title='{parsed.get('paper_title') or '-'}', institution='{parsed.get('university') or '-'}'",
                    "INFO",
                )
            return parsed
        except Exception as exc:
            log("metadata", f"Source archive metadata fallback failed: {exc}", "WARN")
            return {}

    def _parse_tex_metadata(self, root: Path) -> dict[str, str]:
        tex_files = sorted(root.rglob("*.tex"), key=lambda path: path.stat().st_size, reverse=True)
        best: dict[str, str] = {}
        best_score = -1
        for tex_path in tex_files[:20]:
            try:
                content = tex_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            title = ""
            authors = ""
            institutions: list[str] = []

            title_match = re.search(r"\\title\*?\{(.+?)\}", content, flags=re.S)
            if title_match:
                title = _clean_source_title(_strip_tex_commands(title_match.group(1)))

            for pattern in [
                r"\\affiliation\*?\{(.+?)\}",
                r"\\institute\*?\{(.+?)\}",
                r"\\affil\*?\{(.+?)\}",
                r"\\address\*?\{(.+?)\}",
            ]:
                for match in re.finditer(pattern, content, flags=re.S):
                    candidate = _strip_tex_commands(match.group(1))
                    if candidate and _looks_like_institution(candidate):
                        institutions.append(candidate)

            author_match = re.search(r"\\author\*?\{(.+?)\}", content, flags=re.S)
            if author_match:
                raw_author = author_match.group(1)
                author_clean = _strip_tex_commands(raw_author)
                author_lines = [part.strip(" ,;") for part in re.split(r"\band\b|\\\\|,", author_clean) if part.strip(" ,;")]
                author_names = []
                for part in author_lines:
                    if _looks_like_institution(part):
                        institutions.append(part)
                        continue
                    if len(part.split()) <= 8:
                        author_names.append(part)
                authors = ", ".join(dict.fromkeys(author_names))

            score = int(bool(title)) + int(bool(authors)) + min(2, len(institutions))
            if score > best_score:
                best_score = score
                dedup_institutions = []
                for item in institutions:
                    if item and item not in dedup_institutions:
                        dedup_institutions.append(item)
                best = {
                    "paper_title": title,
                    "authors": authors,
                    "university": " / ".join(dedup_institutions[:3]),
                }
        return best

    def _pdf_frontmatter_metadata(self, job: dict, paper_url: str, log: LogFn) -> dict[str, str]:
        pdf_url = self._pdf_candidate_url(paper_url)
        if not pdf_url:
            return {}
        artifact_dir = Path(str(job.get("artifact_dir") or self.runtime.config.artifacts_dir / str(job.get("id") or "unknown")))
        pdf_path = artifact_dir / "metadata-frontmatter.pdf"
        try:
            self._download_binary(pdf_url, pdf_path)
            doc = fitz.open(pdf_path)
            try:
                text = "\n".join(doc.load_page(idx).get_text("text") for idx in range(min(2, len(doc))))
            finally:
                doc.close()
        except Exception as exc:
            log("metadata", f"PDF frontmatter metadata fallback failed: {exc}", "WARN")
            return {}

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        institutions = []
        authors = ""
        title = ""
        for line in lines[:40]:
            if not title and len(line.split()) >= 4 and not _looks_like_institution(line) and len(line) < 220:
                if not re.search(r"^\d+$", line) and not line.lower().startswith("abstract"):
                    title = line
            if _looks_like_institution(line):
                institutions.append(line)
        for idx, line in enumerate(lines[:20]):
            if "@" in line or _looks_like_institution(line):
                continue
            if "," in line and len(line.split(",")) >= 2 and len(line) < 220:
                authors = line
                break
            if idx > 0 and lines[idx - 1] == title:
                authors = line
                break
        dedup_institutions = []
        for item in institutions:
            item = item.strip(" ,;")
            if item and item not in dedup_institutions:
                dedup_institutions.append(item)
        parsed = {
            "paper_title": _clean_source_title(title),
            "authors": authors.strip(),
            "university": " / ".join(dedup_institutions[:3]),
        }
        if parsed["university"]:
            log("metadata", f"Recovered institution from PDF frontmatter: {parsed['university']}", "INFO")
        return parsed

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

    def _query_structure_analysis(self, notebook_id: str, source_id: str, log: LogFn, *, archetype: str) -> dict[str, str]:
        log("structure", f"Analyzing paper structure for source {source_id}", "INFO")
        question = self.runtime.prompt_loader.load(self.runtime.config.structure_prompt_file)
        structure = {
            "archetype": archetype,
            "background": "medium",
            "method": "medium",
            "experiment": "medium",
            "results": "medium",
            "conclusion": "medium",
        }
        try:
            payload = self._query_nlm_answer(
                notebook_id,
                source_id,
                question,
                command_timeout=180,
                process_timeout=210.0,
                error_message="structure query failed",
            )
        except RuntimeError:
            log("structure", "Structure analysis failed; falling back to heuristic defaults", "WARN")
            return structure
        answer = str(payload.get("answer") or "")
        parsed_archetype = _extract_field([r"Archetype:\s*(.+)"], answer, archetype).strip().lower()
        if parsed_archetype in {"systems", "evaluation", "safety", "tuning", "retrieval", "general"}:
            structure["archetype"] = parsed_archetype
        structure["background"] = _normalize_length_label(_extract_field([r"Background Length:\s*(.+)"], answer, "medium"))
        structure["method"] = _normalize_length_label(_extract_field([r"Method Length:\s*(.+)"], answer, "medium"))
        structure["experiment"] = _normalize_length_label(_extract_field([r"Experiment Length:\s*(.+)"], answer, "medium"))
        structure["results"] = _normalize_length_label(_extract_field([r"Results Length:\s*(.+)"], answer, "medium"))
        structure["conclusion"] = _normalize_length_label(_extract_field([r"Conclusion Length:\s*(.+)"], answer, "medium"))
        log(
            "structure",
            f"Structure emphasis: bg={structure['background']}, method={structure['method']}, exp={structure['experiment']}, results={structure['results']}, conclusion={structure['conclusion']}",
            "INFO",
        )
        return structure

    def _section_guidance_text(self, structure: dict[str, str]) -> str:
        return "\n".join(
            [
                f"- 背景与动机: {structure.get('background', 'medium')}",
                f"- 方法与系统设计: {structure.get('method', 'medium')}",
                f"- 实验设置: {structure.get('experiment', 'medium')}",
                f"- 结果与分析: {structure.get('results', 'medium')}",
                f"- 总结与思考: {structure.get('conclusion', 'medium')}",
            ]
        )

    def _query_notes(self, notebook_id: str, source_id: str, log: LogFn, *, archetype: str, section_guidance: str) -> str:
        log("notes", f"Generating Chinese notes for source {source_id}", "INFO")
        archetype_requirements = {
            "systems": "重点说明系统边界、data/control plane、核心工作流、部署机制、hot-swap 或运行时反馈闭环。",
            "evaluation": "重点说明 benchmark 构造、任务定义、数据来源、指标、baseline 强度、实验有效性与 threats to validity。",
            "safety": "重点说明风险类别、攻击/失效模式、安全边界、评测协议、部署风险与防御启发。",
            "tuning": "重点说明搜索空间、反馈信号、优化循环、warm-start/收敛性、系统收益与成本权衡。",
            "retrieval": "重点说明记忆/检索架构、索引或缓存机制、上下文管理、评测协议与系统权衡。",
            "general": "重点说明问题定义、核心方法、实验设计、结果、局限性与工程含义。",
        }
        question = self.runtime.prompt_loader.load(
            self.runtime.config.notes_prompt_file,
            archetype=archetype,
            archetype_requirement=archetype_requirements.get(archetype, archetype_requirements["general"]),
            section_guidance=section_guidance,
        )
        payload = self._query_nlm_answer(
            notebook_id,
            source_id,
            question,
            command_timeout=240,
            process_timeout=270.0,
            error_message="notes query failed",
        )
        return _polish_notes_markdown(str(payload.get("answer") or ""))

    def _query_nlm_answer(
        self,
        notebook_id: str,
        source_id: str,
        question: str,
        *,
        command_timeout: int,
        process_timeout: float,
        error_message: str,
    ) -> dict:
        result = self.runtime.run(
            [
                "nlm",
                "notebook",
                "query",
                str(notebook_id),
                "--source-ids",
                source_id,
                "--timeout",
                str(command_timeout),
                "--json",
                question,
            ],
            timeout=process_timeout,
        )
        if not result.ok:
            raise RuntimeError((result.stderr or result.stdout).strip() or error_message)
        return _parse_nlm_query_output(result.stdout)

    def _build_note_content(
        self,
        job: dict,
        source_info: dict[str, str],
        metadata: dict[str, str],
        notes: str,
        *,
        assets: AssetList | None = None,
        archive_topic: str = '',
        log: LogFn | None = None,
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
            body = self._inject_figure_section(body, assets, log=log)
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
        )
        cleaned = re.sub(
            r"## 论文基本信息\s+.*?(?=\n##\s|\Z)",
            info_block.strip(),
            cleaned,
            flags=re.S,
        )
        method_subheadings = {
            "## 3. 方法与系统设计\n* **双平面系统架构": "## 3. 方法与系统设计\n### 3.1 双平面架构\n* **双平面系统架构",
            "\n* **基于评估器的运行时反馈闭环": "\n### 3.2 反馈闭环与程序合成\n* **基于评估器的运行时反馈闭环",
            "\n* **热启动与多级安全机制": "\n### 3.3 热启动与安全机制\n* **热启动与多级安全机制",
        }
        for old, new in method_subheadings.items():
            cleaned = cleaned.replace(old, new)
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

    def _agent_figure_placement(self, assets: AssetList, log: LogFn) -> dict[str, str]:
        if self.runtime.config.agent_backend != "claude-glm" or not assets:
            return {}

        figure_info_lines = []
        for i, asset in enumerate(assets, 1):
            name = asset.get("source_name", f"figure-{i}")
            caption = asset.get("caption", "")
            section = asset.get("paper_section", "")
            subsection = asset.get("paper_subsection", "")
            figure_info_lines.append(
                f"{i}. 文件名: {name} | caption: {caption[:100]} | "
                f"原文章节: {section} {subsection}"
            )
        figure_info = "\n".join(figure_info_lines)

        prompt = self.runtime.prompt_loader.load(
            self.runtime.config.figure_placement_prompt_file,
            figure_info=figure_info,
        )
        command_parts = shlex.split(self.runtime.config.claude_glm_command)
        env: dict[str, str] = {}
        while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
            key, value = command_parts.pop(0).split("=", 1)
            env[key] = value
        if not command_parts:
            return {}

        result = self.runtime.run(
            [*command_parts, "-p", "--output-format", "text", prompt],
            env=env,
            cwd=self.runtime.config.base_dir,
            timeout=min(self.runtime.config.agent_timeout_seconds, 60.0),
        )
        if not result.ok:
            log("figures", "Agent figure placement failed, using heuristic fallback", "WARN")
            return {}

        output = (result.stdout or "").strip()
        json_match = re.search(r"\[.*?\]", output, re.S)
        if not json_match:
            log("figures", "Agent figure placement returned non-JSON", "WARN")
            return {}

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            log("figures", "Agent figure placement returned invalid JSON", "WARN")
            return {}

        if not isinstance(parsed, list):
            return {}

        mapping: dict[str, str] = {}
        for item in parsed:
            fig_id = str(item.get("figure_id") or "").strip()
            target = str(item.get("target_section") or "").strip()
            if fig_id and target in ("background", "method", "experiment", "results", "conclusion"):
                mapping[fig_id] = target

        if mapping:
            log("figures", f"Agent reclassified {len(mapping)} figures: {mapping}", "INFO")
        return mapping

    def _inject_figure_section(self, body: str, assets: AssetList, *, log: LogFn | None = None) -> str:
        # Agent reclassification (overrides heuristic placement_target)
        agent_log = log or (lambda s, m, l: None)
        agent_mapping = self._agent_figure_placement(assets, agent_log)
        if agent_mapping:
            for asset in assets:
                source_name = asset.get("source_name", "")
                if source_name in agent_mapping:
                    old_target = asset.get("placement_target", "")
                    asset["placement_target"] = agent_mapping[source_name]
                    agent_log("figures", f"Overrode placement for {source_name}: {old_target} -> {agent_mapping[source_name]}", "INFO")
                else:
                    agent_log("figures", f"No agent match for source_name='{source_name}', keys={list(agent_mapping.keys())[:5]}", "WARN")

        lines = body.splitlines()
        heading_map = {
            'summary': '## 1. 整体概括',
            'background': '## 2. 背景与动机',
            'method': '## 3. 方法与系统设计',
            'experiment': '## 4. 实验设置',
            'results': '## 5. 结果与分析',
            'conclusion': '## 6. 总结与思考',
        }
        fallback_order = ['background', 'method', 'experiment', 'results']
        section_ranges: dict[str, tuple[int, int]] = {}
        heading_positions: list[tuple[str, int]] = []
        for section_key, heading_prefix in heading_map.items():
            for idx, line in enumerate(lines):
                if line.startswith(heading_prefix):
                    heading_positions.append((section_key, idx))
                    break
        heading_positions.sort(key=lambda item: item[1])
        for pos, (section_key, start) in enumerate(heading_positions):
            end = heading_positions[pos + 1][1] if pos + 1 < len(heading_positions) else len(lines)
            section_ranges[section_key] = (start, end)

        assets_by_section: dict[str, list[dict[str, str]]] = {}
        for idx, asset in enumerate(assets, start=1):
            cleaned_caption = _clean_figure_caption(asset.get("caption") or "")
            asset["display_caption"] = cleaned_caption
            section_key = asset.get('placement_target') or asset.get('section_key') or fallback_order[min(idx - 1, len(fallback_order) - 1)]
            assets_by_section.setdefault(section_key, []).append(asset)

        placements: list[tuple[int, dict[str, str]]] = []
        for section_key, section_assets in assets_by_section.items():
            section_start, section_end = section_ranges.get(section_key, (0, len(lines)))
            anchor_positions = self._figure_anchor_positions(lines, section_start, section_end, section_assets)
            for asset, insert_at in zip(section_assets, anchor_positions, strict=False):
                placements.append((insert_at, asset))

        placements.sort(key=lambda item: item[0])
        insertions: dict[int, list[str]] = {}
        for figure_index, (insert_at, asset) in enumerate(placements, start=1):
            block = self._render_figure_block(asset, figure_index)
            insertions.setdefault(insert_at, []).extend(block)

        output: list[str] = []
        for idx, line in enumerate(lines):
            output.append(line)
            if idx + 1 in insertions:
                output.extend(insertions[idx + 1])
        if len(lines) in insertions:
            output.extend(insertions[len(lines)])
        return "\n".join(output).strip() + "\n"

    def _figure_anchor_positions(
        self,
        lines: list[str],
        section_start: int,
        section_end: int,
        assets: AssetList,
    ) -> list[int]:
        candidate_positions: list[tuple[int, str]] = []
        for idx in range(section_start + 1, section_end):
            line = lines[idx]
            if line.startswith("## "):
                break
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("* ", "- ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ")):
                candidate_positions.append((idx + 1, stripped))
                continue
            if stripped.startswith("<figure"):
                continue
            candidate_positions.append((idx + 1, stripped))
        if not candidate_positions:
            return [section_start + 1 for _ in assets]

        remaining_positions = candidate_positions[:]
        chosen: list[int] = []
        for asset_index, asset in enumerate(assets):
            keywords = self._figure_match_text(asset)
            preferred = self._preferred_anchor_patterns(asset)
            if preferred:
                matched = [pos for pos, text in remaining_positions if any(token in text.lower() for token in preferred)]
                if matched:
                    selected = matched[0] if self._prefer_first_anchor(asset) else matched[-1]
                    chosen.append(selected)
                    remaining_positions = [item for item in remaining_positions if item[0] != selected]
                    continue
            best_pos = None
            best_score = -1.0
            for pos, text in remaining_positions:
                score = _overlap_score(_route_tokens(keywords), _route_tokens(text))
                if score > best_score:
                    best_score = score
                    best_pos = pos
            if best_pos is None or best_score <= 0:
                ratio = (asset_index + 1) / (len(assets) + 1)
                fallback_idx = min(int(ratio * len(candidate_positions)), len(candidate_positions) - 1)
                best_pos = candidate_positions[fallback_idx][0]
            chosen.append(best_pos)
            remaining_positions = [item for item in remaining_positions if item[0] != best_pos]
        chosen.sort()
        return chosen

    def _figure_match_text(self, asset: dict[str, str]) -> str:
        return " ".join(
            part
            for part in [
                str(asset.get("display_caption") or ""),
                str(asset.get("paper_section") or ""),
                str(asset.get("paper_subsection") or ""),
                str(asset.get("source_name") or ""),
            ]
            if part
        )

    def _preferred_anchor_patterns(self, asset: dict[str, str]) -> list[str]:
        source_name = str(asset.get("source_name") or "").lower()
        caption = str(asset.get("display_caption") or asset.get("caption") or "").lower()
        section_text = " ".join(
            part.lower()
            for part in [
                str(asset.get("paper_section") or ""),
                str(asset.get("paper_subsection") or ""),
            ]
            if part
        )
        text = " ".join(part for part in [source_name, caption, section_text] if part)
        if "runtime_dynamic" in source_name or "workload dynamics" in caption:
            return ["同构集群", "distserve", "工作负载", "流量", "综合性能"]
        if "motivation" in source_name:
            return ["权衡", "运行时权衡", "设计动机", "静态策略", "trade-off"]
        if "online_workflow" in source_name:
            return ["控制面", "control plane"]
        if "execution_model" in source_name:
            return ["评估器", "evaluator"]
        if "synthesis_workflow" in source_name:
            return ["artifact feedback", "伪像反馈", "评估器", "evaluator", "反馈闭环"]
        if "impl" in source_name or "deployment" in section_text:
            return ["部署机制", "deployment", "热插拔", "hot-swap"]
        if any(token in text for token in ["trade-off", "tradeoff", "runtime dynamic", "workload dynamics", "motivation"]):
            return ["trade-off", "权衡", "运行时动态", "运行时权衡", "设计动机"]
        if any(token in text for token in ["two-plane", "system architecture", "architecture", "overview"]):
            return ["双平面", "系统架构", "two-plane", "architecture"]
        if any(token in text for token in ["execution model", "data plane", "control plane"]):
            return ["控制面", "data plane", "control plane", "数据面"]
        if any(token in text for token in ["program synthesis", "workflow", "evaluator"]):
            return ["核心工作流", "评估器", "反馈闭环", "program synthesis", "工作流"]
        if "hot-swap" in text:
            return ["部署机制", "hot-swap", "热插拔"]
        if any(token in text for token in ["workload", "phase", "performance across", "bursty", "steady"]):
            return ["综合性能", "性能提升", "流量", "工作负载", "结果"]
        return []

    def _prefer_first_anchor(self, asset: dict[str, str]) -> bool:
        source_name = str(asset.get("source_name") or "").lower()
        return "motivation" in source_name or "runtime_dynamic" in source_name

    def _render_figure_block(self, asset: dict[str, str], figure_index: int) -> list[str]:
        caption = _figure_caption_text(asset, figure_index)
        alt_text = _figure_alt_text(asset, figure_index)
        block = [""]
        if caption:
            block.append(f"> [!figure]- 图 {figure_index}. {caption}")
        else:
            block.append(f"> [!figure]- 图 {figure_index}")
        block.append(f"> ![]({asset['markdown_path']})")
        block.append("")
        return block

    def _agent_notes_preflight(
        self,
        metadata: dict[str, str],
        notes: str,
        topic_list: list[str],
        log: LogFn,
    ) -> dict | None:
        if self.runtime.config.agent_backend != "claude-glm":
            return None

        topic_list_str = "\n".join(f"- {t}" for t in topic_list)
        prompt = self.runtime.prompt_loader.load(
            self.runtime.config.notes_preflight_prompt_file,
            paper_title=metadata.get("paper_title", ""),
            venue=metadata.get("conference", ""),
            year=metadata.get("year", ""),
            institution=metadata.get("university", ""),
            authors=metadata.get("authors", ""),
            notes_head=notes[:500],
            topic_list=topic_list_str or "(no topics)",
        )

        command_parts = shlex.split(self.runtime.config.claude_glm_command)
        env: dict[str, str] = {}
        while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
            key, value = command_parts.pop(0).split("=", 1)
            env[key] = value
        if not command_parts:
            return None

        result = self.runtime.run(
            [*command_parts, "-p", "--output-format", "text", prompt],
            env=env,
            cwd=self.runtime.config.base_dir,
            timeout=min(self.runtime.config.agent_timeout_seconds, 60.0),
        )
        if not result.ok:
            log("preflight", "Agent notes preflight failed, using heuristic fallback", "WARN")
            return None

        output = (result.stdout or "").strip()
        json_match = re.search(r"\{[^{}]*\}", output, re.S)
        if not json_match:
            log("preflight", "Agent notes preflight returned non-JSON", "WARN")
            return None

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            log("preflight", "Agent notes preflight returned invalid JSON", "WARN")
            return None

        fourth = str(parsed.get("fourth_title") or "").strip()
        slug = str(parsed.get("title_slug") or "").strip()
        topic = str(parsed.get("topic_folder") or "").strip()
        if not fourth or not slug or not topic:
            log("preflight", "Agent notes preflight returned incomplete data", "WARN")
            return None

        log("preflight", f"Agent confirmed L3 title: {fourth}, slug: {slug}, topic: {topic}", "INFO")
        return {"fourth_title": fourth, "title_slug": slug, "topic_folder": topic}

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

    def _resolve_output_target(self, job: dict, metadata: dict[str, str], archive_topic: str, *, preflight: dict | None = None) -> OutputPlan:
        repo = self.runtime.config.obsidian_sync_repo
        topic_dir = _topic_dir_slug(archive_topic)
        notes_root = repo / self.runtime.config.obsidian_sync_subdir / topic_dir
        notes_root.mkdir(parents=True, exist_ok=True)
        conference_slug = _slug(metadata["conference"].replace(" ", "-")) or "arXiv"
        agent_slug = preflight.get("title_slug", "") if preflight else ""
        title_slug = _slug(agent_slug) if agent_slug else _short_title_slug(metadata["paper_title"])
        base_name = f"{metadata['year']}-{conference_slug}-{title_slug}"
        target = notes_root / f"{base_name}.md"
        version = 2
        while target.exists():
            target = notes_root / f"{base_name}-v{version}.md"
            version += 1
        relative_output = target.relative_to(repo)
        assets_dir = repo / self.runtime.config.obsidian_sync_subdir / "_assets" / topic_dir / target.stem
        relative_assets_dir = assets_dir.relative_to(repo)
        return OutputPlan(
            target=target,
            relative_output=relative_output,
            assets_dir=assets_dir,
            relative_assets_dir=relative_assets_dir,
            taxonomy_topic=archive_topic,
            taxonomy_topic_dir=topic_dir,
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
        markdown_path = Path("..") / "_assets" / output_plan.taxonomy_topic_dir / output_plan.target.stem / asset_path.name
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
            markdown_path = Path("..") / "_assets" / output_plan.taxonomy_topic_dir / output_plan.target.stem / asset_path.name
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

    def _export_review_pdf(self, job: dict, output_plan: OutputPlan, log: LogFn) -> str:
        artifact_dir = Path(str(job.get("artifact_dir") or self.runtime.config.artifacts_dir / str(job.get("id") or "unknown")))
        pdf_dir = artifact_dir / "pdfcheck"
        pdf_path = pdf_dir / f"{output_plan.target.stem}.pdf"
        script_path = self.runtime.config.base_dir / "scripts" / "export_note_pdf.py"
        result = self.runtime.run(
            [
                "python3",
                str(script_path),
                str(output_plan.target),
                str(pdf_path),
            ],
            timeout=60.0,
        )
        if not result.ok:
            log("readability", f"Failed to export review PDF: {(result.stderr or result.stdout).strip() or 'unknown error'}", "WARN")
            return ""
        log("readability", f"Exported review PDF to {pdf_path}", "INFO")
        return str(pdf_path)

    def _review_readability(self, job: dict, output_plan: OutputPlan, review_pdf_path: str, log: LogFn) -> tuple[str, str]:
        if not review_pdf_path:
            return "", ""
        if self.runtime.config.agent_backend != "claude-glm":
            log("readability", f"Skipping readability review for unsupported backend '{self.runtime.config.agent_backend}'", "WARN")
            return "", ""

        artifact_dir = Path(str(job.get("artifact_dir") or self.runtime.config.artifacts_dir / str(job.get("id") or "unknown")))
        review_path = artifact_dir / "readability_review.txt"
        pdf_text = self._extract_pdf_text(Path(review_pdf_path))
        if not pdf_text:
            log("readability", "Skipping readability review because rendered PDF text could not be extracted", "WARN")
            return "", ""
        prompt = self.runtime.prompt_loader.load(
            self.runtime.config.readability_prompt_file,
            note_path=str(output_plan.target),
            pdf_path=review_pdf_path,
        )
        raw_markdown = output_plan.target.read_text(encoding='utf-8')
        review_markdown = re.sub(r"^---\n.*?\n---\n?", "", raw_markdown, flags=re.S)
        prompt = (
            f"{prompt}\n\n"
            f"下面是 markdown 原文，请按可读性审读，不要重写全文：\n"
            f"```markdown\n{review_markdown[:20000]}\n```\n\n"
            f"下面是渲染后 PDF 抽取出的正文文本，请优先依据它判断版面阅读体验：\n"
            f"```text\n{pdf_text[:20000]}\n```"
        )
        command_parts = shlex.split(self.runtime.config.claude_glm_command)
        env: dict[str, str] = {}
        while command_parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", command_parts[0]):
            key, value = command_parts.pop(0).split("=", 1)
            env[key] = value
        if not command_parts:
            log("readability", "Readability review skipped: empty agent command", "WARN")
            return "", ""
        result = self.runtime.run(
            [
                *command_parts,
                "-p",
                "--output-format",
                "text",
                prompt,
            ],
            env=env,
            cwd=self.runtime.config.base_dir,
            timeout=min(self.runtime.config.agent_timeout_seconds, 120.0),
        )
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "readability review failed"
            log("readability", f"Readability review failed: {message}", "WARN")
            return "", ""
        review_agent_dir = artifact_dir / "readability_agent"
        review_agent_dir.mkdir(parents=True, exist_ok=True)
        (review_agent_dir / "claude.stdout").write_text(result.stdout or "", encoding="utf-8")
        (review_agent_dir / "claude.stderr").write_text(result.stderr or "", encoding="utf-8")
        review_text = (result.stdout or "").strip()
        if not review_text:
            log("readability", "Readability review returned empty output", "WARN")
            return "", ""
        review_path.write_text(review_text + "\n", encoding="utf-8")
        summary = self._summarize_readability_review(review_text)
        if summary:
            log("readability", f"Top fixes: {summary}", "INFO")
        else:
            log("readability", f"Saved readability review to {review_path}", "INFO")
        return str(review_path), summary

    def _summarize_readability_review(self, review_text: str) -> str:
        top_fixes: list[str] = []
        capture = False
        for raw_line in review_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if re.search(r"\btop\b.*\bfix", lowered):
                capture = True
                continue
            if capture and re.match(r"^(?:[-*]\s+|\d+\.\s+)", line):
                top_fixes.append(re.sub(r"^(?:[-*]\s+|\d+\.\s+)", "", line))
                if len(top_fixes) >= 2:
                    break
            elif capture and top_fixes:
                break
        if top_fixes:
            return "；".join(top_fixes)
        for raw_line in review_text.splitlines():
            line = raw_line.strip()
            if line:
                return line[:240]
        return ""

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        try:
            doc = fitz.open(pdf_path)
            try:
                chunks: list[str] = []
                for page_index in range(min(len(doc), 12)):
                    page = doc.load_page(page_index)
                    text = page.get_text("text")
                    text = re.sub(r"\s+\n", "\n", text)
                    text = re.sub(r"\n{3,}", "\n\n", text)
                    text = text.strip()
                    if text:
                        chunks.append(f"[Page {page_index + 1}]\n{text}")
                return "\n\n".join(chunks)
            finally:
                doc.close()
        except Exception:
            return ""

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
