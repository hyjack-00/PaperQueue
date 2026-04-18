from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _default_framework_version() -> str:
    override = os.environ.get("PAPER_QUEUE_FRAMEWORK_VERSION")
    if override:
        return override
    try:
        return metadata.version("paper-reading-queue")
    except metadata.PackageNotFoundError:
        return "0.1.1"


def _load_file_config() -> dict:
    config_path = Path(os.environ.get("PAPER_QUEUE_CONFIG_FILE", BASE_DIR / "paper_queue" / "config" / "defaults.json"))
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


FILE_CONFIG = _load_file_config()


def _config_get(path: str, default):
    node = FILE_CONFIG
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


@dataclass(slots=True)
class Settings:
    base_dir: Path = BASE_DIR
    app_title: str = "Paper Reading Queue"
    config_file: Path = Path(os.environ.get("PAPER_QUEUE_CONFIG_FILE", BASE_DIR / "paper_queue" / "config" / "defaults.json"))
    host: str = os.environ.get("PAPER_QUEUE_HOST", "0.0.0.0")
    port: int = int(os.environ.get("PAPER_QUEUE_PORT", "8000"))
    db_path: Path = Path(os.environ.get("PAPER_QUEUE_DB", BASE_DIR / "var" / "queue.db"))
    logs_dir: Path = Path(os.environ.get("PAPER_QUEUE_LOG_DIR", BASE_DIR / "var" / "job_logs"))
    artifacts_dir: Path = Path(
        os.environ.get("PAPER_QUEUE_ARTIFACT_DIR", BASE_DIR / "var" / "job_artifacts")
    )
    claude_config_dir: Path = Path(
        os.environ.get("CLAUDE_GLM_CONFIG_DIR", "/home/agent-user/.claude-glm")
    )
    agent_backend: str = os.environ.get("PAPER_QUEUE_AGENT_BACKEND", _config_get("agent.backend", "claude-glm"))
    claude_glm_command: str = os.environ.get(
        "CLAUDE_GLM_COMMAND",
        str(_config_get("agent.command", "CLAUDE_CONFIG_DIR=/home/agent-user/.claude-glm claude --dangerously-skip-permissions")),
    )
    claude_model: str = os.environ.get("CLAUDE_GLM_MODEL", str(_config_get("agent.model", "glm-5.1")))
    skill_name: str = os.environ.get("PAPER_QUEUE_SKILL_NAME", str(_config_get("skill.name", "notebooklm-paper-reader")))
    skill_source_dir: Path = Path(
        os.environ.get("PAPER_QUEUE_SKILL_DIR", str(_config_get("skill.source_dir", BASE_DIR / "notebooklm-paper-reader")))
    )
    obsidian_sync_repo: Path = Path(
        os.environ.get("OBSIDIAN_SYNC_REPO", "/workspace/obsidian_sync")
    )
    obsidian_sync_branch: str = os.environ.get("OBSIDIAN_SYNC_BRANCH", "main")
    obsidian_sync_subdir: str = os.environ.get("OBSIDIAN_SYNC_SUBDIR", str(_config_get("storage.subdir", "paper")))
    framework_version: str = _default_framework_version()
    evaluation_assets_dir: Path = Path(
        os.environ.get(
            "PAPER_QUEUE_EVAL_ASSETS_DIR",
            str(BASE_DIR / str(_config_get("evaluation.assets_dir", "benchmarks/assets"))),
        )
    )
    evaluation_paragraph_batch_size: int = int(
        os.environ.get("PAPER_QUEUE_EVAL_PARAGRAPH_BATCH_SIZE", str(_config_get("evaluation.paragraph_batch_size", "12")))
    )
    evaluation_self_review_rounds: int = int(
        os.environ.get("PAPER_QUEUE_EVAL_SELF_REVIEW_ROUNDS", str(_config_get("evaluation.self_review_rounds", "3")))
    )
    evaluation_max_paragraph_chars: int = int(
        os.environ.get("PAPER_QUEUE_EVAL_MAX_PARAGRAPH_CHARS", str(_config_get("evaluation.max_paragraph_chars", "1800")))
    )
    evaluation_agent_timeout_seconds: float = float(
        os.environ.get(
            "PAPER_QUEUE_EVAL_AGENT_TIMEOUT_SECONDS",
            str(_config_get("evaluation.agent_timeout_seconds", "45")),
        )
    )
    evaluation_swiftscholar_pdf_dir: Path = Path(
        os.environ.get(
            "PAPER_QUEUE_EVAL_SWIFTSCHOLAR_PDF_DIR",
            str(_config_get("evaluation.swiftscholar_pdf_dir", "/workspace/paper_reading/benchmarks/swiftscholar_pdfs")),
        )
    )
    worker_poll_seconds: float = float(os.environ.get("PAPER_QUEUE_WORKER_POLL", "2.0"))
    recent_log_lines: int = int(os.environ.get("PAPER_QUEUE_RECENT_LOG_LINES", "8"))
    auth_cache_ttl_seconds: float = float(os.environ.get("PAPER_QUEUE_AUTH_CACHE_TTL", "60"))
    notebook_cache_ttl_seconds: float = float(os.environ.get("PAPER_QUEUE_NOTEBOOK_CACHE_TTL", "300"))
    auth_check_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_AUTH_CHECK_TIMEOUT", "15"))
    notebook_list_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_NOTEBOOK_LIST_TIMEOUT", "15"))
    notebook_describe_timeout_seconds: float = float(
        os.environ.get("PAPER_QUEUE_NOTEBOOK_DESCRIBE_TIMEOUT", "20")
    )
    notebook_summary_cache_ttl_seconds: float = float(
        os.environ.get("PAPER_QUEUE_NOTEBOOK_SUMMARY_CACHE_TTL", "21600")
    )
    git_remote_check_timeout_seconds: float = float(
        os.environ.get("PAPER_QUEUE_GIT_REMOTE_CHECK_TIMEOUT", "30")
    )
    agent_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_AGENT_TIMEOUT_SECONDS", str(_config_get("agent.timeout_seconds", "1800"))))
    waiting_auth_recheck_seconds: float = float(
        os.environ.get("PAPER_QUEUE_WAITING_AUTH_RECHECK", "60")
    )
    prompt_dir: Path = Path(os.environ.get("PAPER_QUEUE_PROMPT_DIR", str(BASE_DIR / "paper_queue" / "prompts")))
    metadata_prompt_file: str = str(_config_get("prompts.metadata", "metadata_v1.txt"))
    metadata_agent_prompt_file: str = str(_config_get("prompts.metadata_agent", "metadata_agent_v1.txt"))
    notes_preflight_prompt_file: str = str(_config_get("prompts.notes_preflight", "notes_preflight_v1.txt"))
    figure_placement_prompt_file: str = str(_config_get("prompts.figure_placement", "figure_placement_v1.txt"))
    notes_prompt_file: str = str(_config_get("prompts.notes", "notes_v1.txt"))
    structure_prompt_file: str = str(_config_get("prompts.structure_analysis", "structure_analysis_v1.txt"))
    readability_prompt_file: str = str(_config_get("prompts.readability_review", "readability_review_v1.txt"))
    benchmark_paragraph_points_prompt_file: str = str(
        _config_get("prompts.benchmark_paragraph_points", "benchmark_paragraph_points_v1.txt")
    )
    benchmark_coverage_prompt_file: str = str(
        _config_get("prompts.benchmark_coverage_review", "benchmark_coverage_review_v1.txt")
    )
    benchmark_placement_prompt_file: str = str(
        _config_get("prompts.benchmark_placement_review", "benchmark_placement_review_v1.txt")
    )
    benchmark_length_prompt_file: str = str(
        _config_get("prompts.benchmark_length_review", "benchmark_length_review_v1.txt")
    )
    routing_prompt_file: str = str(_config_get("prompts.routing", "routing_v1.txt"))

    @property
    def skill_install_dir(self) -> Path:
        return self.claude_config_dir / "skills"

    @property
    def skill_install_path(self) -> Path:
        return self.skill_install_dir / self.skill_name

    @property
    def obsidian_notes_root(self) -> Path:
        return self.obsidian_sync_repo / self.obsidian_sync_subdir


settings = Settings()
