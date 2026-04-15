from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(slots=True)
class Settings:
    base_dir: Path = BASE_DIR
    app_title: str = "Paper Reading Queue"
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
    claude_glm_command: str = os.environ.get(
        "CLAUDE_GLM_COMMAND",
        "CLAUDE_CONFIG_DIR=/home/agent-user/.claude-glm claude --dangerously-skip-permissions",
    )
    claude_model: str = os.environ.get("CLAUDE_GLM_MODEL", "glm-5.1")
    skill_name: str = os.environ.get("PAPER_QUEUE_SKILL_NAME", "notebooklm-paper-reader")
    skill_source_dir: Path = Path(
        os.environ.get("PAPER_QUEUE_SKILL_DIR", BASE_DIR / "notebooklm-paper-reader")
    )
    nextcloud_compose_file: Path = Path(
        os.environ.get("NEXTCLOUD_COMPOSE_FILE", "/workspace/nextcloud/docker-compose.yml")
    )
    nextcloud_data_dir: Path = Path(
        os.environ.get("NEXTCLOUD_DATA_DIR", "/workspace/nextcloud/data/data/admin/files")
    )
    vault_root_name: str = os.environ.get("PAPER_QUEUE_VAULT_ROOT", "MAIN")
    paper_subdir: str = os.environ.get("PAPER_QUEUE_PAPER_SUBDIR", "paper")
    worker_poll_seconds: float = float(os.environ.get("PAPER_QUEUE_WORKER_POLL", "2.0"))
    recent_log_lines: int = int(os.environ.get("PAPER_QUEUE_RECENT_LOG_LINES", "8"))
    auth_cache_ttl_seconds: float = float(os.environ.get("PAPER_QUEUE_AUTH_CACHE_TTL", "60"))
    notebook_cache_ttl_seconds: float = float(os.environ.get("PAPER_QUEUE_NOTEBOOK_CACHE_TTL", "300"))
    auth_check_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_AUTH_CHECK_TIMEOUT", "15"))
    notebook_list_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_NOTEBOOK_LIST_TIMEOUT", "15"))
    agent_timeout_seconds: float = float(os.environ.get("PAPER_QUEUE_AGENT_TIMEOUT_SECONDS", "1800"))
    nextcloud_recheck_seconds: float = float(os.environ.get("PAPER_QUEUE_NEXTCLOUD_RECHECK", "60"))
    waiting_auth_recheck_seconds: float = float(
        os.environ.get("PAPER_QUEUE_WAITING_AUTH_RECHECK", "60")
    )

    @property
    def skill_install_dir(self) -> Path:
        return self.claude_config_dir / "skills"

    @property
    def skill_install_path(self) -> Path:
        return self.skill_install_dir / self.skill_name

    @property
    def vault_root(self) -> Path:
        return self.nextcloud_data_dir / self.vault_root_name

    @property
    def paper_root(self) -> Path:
        return self.vault_root / self.paper_subdir


settings = Settings()
