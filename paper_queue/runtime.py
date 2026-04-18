from __future__ import annotations

import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings, settings
from .db import JobStore
from .prompt_loader import PromptLoader
from .workflow import PaperWorkflow


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runtime:
    def __init__(self, config: Settings) -> None:
        self.config = config
        self.prompt_loader = PromptLoader(config.prompt_dir)
        self._cache_lock = threading.Lock()
        self._auth_cache: tuple[float, bool, str] | None = None
        self._notebook_cache: tuple[float, list[dict[str, str]], str | None] | None = None
        self._notebook_summary_cache: dict[str, tuple[float, str]] = {}

    def run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = 120.0,
    ) -> CommandResult:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        try:
            proc = subprocess.run(
                args,
                text=True,
                capture_output=True,
                env=full_env,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
            )
            return CommandResult(args=args, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return CommandResult(args=args, returncode=124, stdout=stdout, stderr=f"{stderr}\ncommand timed out")

    def run_shell(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = 120.0,
    ) -> CommandResult:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        return self.run(["/bin/bash", "-lc", command], env=full_env, cwd=cwd, timeout=timeout)

    def run_shell_streaming(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
        log_stdout: callable | None = None,
        log_stderr: callable | None = None,
        artifact_dir: Path | None = None,
    ) -> CommandResult:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "command.txt").write_text(command, encoding="utf-8")
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            bufsize=1,
        )
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None
        assert proc.stderr is not None
        selector.register(proc.stdout, selectors.EVENT_READ, ("stdout", log_stdout, stdout_lines))
        selector.register(proc.stderr, selectors.EVENT_READ, ("stderr", log_stderr, stderr_lines))
        deadline = None if timeout is None else time.monotonic() + timeout
        timed_out = False

        while selector.get_map():
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if deadline is not None and remaining == 0.0:
                timed_out = True
                proc.kill()
                break
            events = selector.select(timeout=remaining if remaining is None or remaining < 1 else 1)
            if not events:
                if proc.poll() is not None and deadline is not None and time.monotonic() < deadline:
                    continue
                if deadline is None:
                    continue
                continue
            for key, _ in events:
                stream_name, callback, sink = key.data
                line = key.fileobj.readline()
                if line == "":
                    selector.unregister(key.fileobj)
                    continue
                sink.append(line)
                if callback:
                    callback(line.rstrip("\n"))

        if timed_out:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            stderr_lines.append("command timed out\n")
        else:
            proc.wait()
            for stream_name, callback, sink, fileobj in (
                ("stdout", log_stdout, stdout_lines, proc.stdout),
                ("stderr", log_stderr, stderr_lines, proc.stderr),
            ):
                remainder = fileobj.read() if fileobj else ""
                if remainder:
                    sink.append(remainder)
                    if callback:
                        for line in remainder.splitlines():
                            callback(line)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        if artifact_dir:
            (artifact_dir / "claude.stdout").write_text(stdout, encoding="utf-8")
            (artifact_dir / "claude.stderr").write_text(stderr, encoding="utf-8")
        return CommandResult(
            args=["/bin/bash", "-lc", command],
            returncode=124 if timed_out else proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _auth_check_uncached(self) -> tuple[bool, str]:
        result = self.run(["nlm", "login", "--check"], timeout=self.config.auth_check_timeout_seconds)
        if result.ok:
            return True, "NotebookLM auth OK"
        message = (result.stderr or result.stdout).strip()
        if result.returncode == 124:
            return False, "NotebookLM auth check timed out"
        if "Authentication expired" in message:
            return False, "NotebookLM auth expired"
        return False, message.splitlines()[-1] if message else "NotebookLM auth check failed"

    def auth_check(self, *, force: bool = False) -> tuple[bool, str]:
        now = time.monotonic()
        with self._cache_lock:
            if not force and self._auth_cache:
                cached_at, ok, message = self._auth_cache
                if now - cached_at < self.config.auth_cache_ttl_seconds:
                    return ok, message
        ok, message = self._auth_check_uncached()
        with self._cache_lock:
            self._auth_cache = (time.monotonic(), ok, message)
        return ok, message

    def notebook_list(self, *, force: bool = False) -> tuple[list[dict[str, str]], str | None]:
        now = time.monotonic()
        with self._cache_lock:
            if not force and self._notebook_cache:
                cached_at, notebooks, error = self._notebook_cache
                if now - cached_at < self.config.notebook_cache_ttl_seconds:
                    return notebooks, error
        result = self.run(
            ["nlm", "notebook", "list", "--json"],
            timeout=self.config.notebook_list_timeout_seconds,
        )
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "failed to list notebooks"
            with self._cache_lock:
                if self._notebook_cache:
                    _, notebooks, _ = self._notebook_cache
                    return notebooks, message
            return [], message
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return [], "invalid notebook JSON from nlm"
        notebooks: list[dict[str, str]] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                notebook_id = str(item.get("id") or item.get("notebook_id") or "")
                title = str(item.get("title") or item.get("name") or notebook_id)
                if notebook_id:
                    notebooks.append({"id": notebook_id, "title": title})
        with self._cache_lock:
            self._notebook_cache = (time.monotonic(), notebooks, None)
        return notebooks, None

    def notebook_summary(self, notebook_id: str, *, force: bool = False) -> tuple[str | None, str | None]:
        now = time.monotonic()
        with self._cache_lock:
            if not force and notebook_id in self._notebook_summary_cache:
                cached_at, summary = self._notebook_summary_cache[notebook_id]
                if now - cached_at < self.config.notebook_summary_cache_ttl_seconds:
                    return summary, None
        result = self.run(
            ["nlm", "notebook", "describe", notebook_id, "--json"],
            timeout=self.config.notebook_describe_timeout_seconds,
        )
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "failed to describe notebook"
            return None, message
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, "invalid notebook summary JSON from nlm"
        value = payload.get("value") if isinstance(payload, dict) else payload
        summary_lines = value.get("summary") if isinstance(value, dict) else None
        summary = " ".join(str(line).strip() for line in summary_lines or [] if str(line).strip())
        with self._cache_lock:
            self._notebook_summary_cache[notebook_id] = (time.monotonic(), summary)
        return summary, None

    def invalidate_notebook_cache(self) -> None:
        with self._cache_lock:
            self._notebook_cache = None
            self._notebook_summary_cache = {}

    def create_notebook(self, title: str) -> tuple[dict[str, str] | None, str | None]:
        before, error = self.notebook_list(force=True)
        if error:
            return None, error
        before_ids = {item["id"] for item in before}
        result = self.run(["nlm", "notebook", "create", title], timeout=60.0)
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "failed to create notebook"
            return None, message
        self.invalidate_notebook_cache()
        after, error = self.notebook_list(force=True)
        if error:
            return None, error
        for item in after:
            if item["title"] == title and item["id"] not in before_ids:
                return item, None
        for item in after:
            if item["title"] == title:
                return item, None
        return None, "created notebook but could not identify it"

    def delete_notebook(self, notebook_id: str) -> tuple[bool, str]:
        result = self.run(["nlm", "notebook", "delete", notebook_id, "--confirm"], timeout=60.0)
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "failed to delete notebook"
            return False, message
        self.invalidate_notebook_cache()
        return True, "deleted"

    def system_status(self) -> dict[str, Any]:
        auth_ok, auth_message = self.auth_check()
        git_ok, git_message = self.git_remote_check()
        skill_ok = (self.config.skill_install_path / "SKILL.md").exists()
        git_repo_exists = (self.config.obsidian_sync_repo / ".git").exists()
        return {
            "auth_ok": auth_ok,
            "auth_message": auth_message,
            "claude_ok": shutil.which("claude") is not None,
            "nlm_ok": shutil.which("nlm") is not None,
            "skill_ok": skill_ok,
            "skill_path": str(self.config.skill_install_path),
            "git_repo_ok": git_repo_exists,
            "git_repo_path": str(self.config.obsidian_sync_repo),
            "git_remote_ok": git_ok,
            "git_remote_message": git_message,
            "git_branch": self.config.obsidian_sync_branch,
        }

    def git_remote_check(self) -> tuple[bool, str]:
        repo = self.config.obsidian_sync_repo
        if not (repo / ".git").exists():
            return False, f"git repo missing: {repo}"
        last_message = "git remote check failed"
        for attempt in range(2):
            result = self.run(
                ["git", "-C", str(repo), "ls-remote", "origin", "HEAD", f"refs/heads/{self.config.obsidian_sync_branch}"],
                timeout=self.config.git_remote_check_timeout_seconds,
            )
            if result.ok:
                if f"refs/heads/{self.config.obsidian_sync_branch}" not in result.stdout:
                    return False, f"remote branch missing: {self.config.obsidian_sync_branch}"
                return True, "git remote reachable"
            last_message = (result.stderr or result.stdout).strip() or "git remote check failed"
            if attempt == 0:
                time.sleep(2)
        return False, last_message

    def artifact_dir(self, job_id: int) -> Path:
        return self.config.artifacts_dir / str(job_id)

    def write_artifact(self, job_id: int, name: str, content: str) -> None:
        artifact_dir = self.artifact_dir(job_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / name).write_text(content, encoding="utf-8")

    def install_skill(self) -> CommandResult:
        install_dir = self.config.skill_install_dir
        source_dir = self.config.skill_source_dir
        command = shell_join(
            [
                "mkdir",
                "-p",
                str(install_dir),
            ]
        )
        result = self.run_shell(command)
        if not result.ok:
            return result
        link_cmd = (
            f"ln -sfn {shlex.quote(str(source_dir))} {shlex.quote(str(self.config.skill_install_path))}"
        )
        return self.run_shell(link_cmd)


class JobRunner:
    def __init__(self, store: JobStore, runtime: Runtime, config: Settings) -> None:
        self.store = store
        self.runtime = runtime
        self.config = config
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_waiting_auth_check = 0.0
        self._last_git_check = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    @property
    def active_job_id(self) -> int | None:
        for job in self.store.running_jobs():
            pid = int(job.get("worker_pid") or 0)
            if pid and self._pid_alive(pid):
                return int(job["id"])
        return None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _log(self, job_id: int, stage: str, message: str, *, level: str = "INFO") -> None:
        timestamp = now_iso()
        self.store.append_log(
            job_id=job_id,
            created_at=timestamp,
            level=level,
            stage=stage,
            message=message,
        )
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.config.logs_dir / f"{job_id}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} [{level}] ({stage}) {message}\n")

    def _update(self, job_id: int, **kwargs: Any) -> None:
        self.store.set_status(job_id, updated_at=now_iso(), **kwargs)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._reconcile_running_jobs()
            self._maybe_requeue_waiting_auth()
            self._maybe_requeue_blocked_git()
            if self.active_job_id is not None:
                time.sleep(self.config.worker_poll_seconds)
                continue
            job = self.store.claim_next_job(now_iso())
            if not job:
                time.sleep(self.config.worker_poll_seconds)
                continue
            self._launch_job(job)

    def _launch_job(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        self._log(job_id, "starting", "Worker claimed job")
        command = [sys.executable, "-m", "paper_queue.worker", str(job_id)]
        proc = subprocess.Popen(
            command,
            cwd=str(self.config.base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.store.attach_worker_pid(job_id, proc.pid, now_iso())
        self._log(job_id, "dispatch", f"Spawned worker PID {proc.pid}")

    def _maybe_requeue_waiting_auth(self) -> None:
        now = time.monotonic()
        if now - self._last_waiting_auth_check < self.config.waiting_auth_recheck_seconds:
            return
        self._last_waiting_auth_check = now
        jobs = self.store.list_jobs()
        if not any(job["status"] == "waiting_auth" for job in jobs):
            return
        auth_ok, _ = self.runtime.auth_check(force=True)
        if auth_ok:
            self.store.requeue_waiting_auth(now_iso())

    def _maybe_requeue_blocked_git(self) -> None:
        now = time.monotonic()
        if now - self._last_git_check < self.config.waiting_auth_recheck_seconds:
            return
        self._last_git_check = now
        jobs = self.store.list_jobs()
        if not any(job["status"] == "blocked_git" for job in jobs):
            return
        git_ok, _ = self.runtime.git_remote_check()
        if git_ok:
            self.store.requeue_blocked_git(now_iso())

    def _reconcile_running_jobs(self) -> None:
        for job in self.store.running_jobs():
            pid = int(job.get("worker_pid") or 0)
            if pid and self._pid_alive(pid):
                continue
            self.store.requeue_job(
                int(job["id"]),
                now_iso(),
                error_message="worker process stopped before completion; requeued",
            )
            self._log(int(job["id"]), "queued", "Worker process missing; job requeued", level="WARN")

    @staticmethod
    def _parse_claude_output(raw: str) -> dict[str, Any] | None:
        for candidate in JobRunner._candidate_json_strings(raw):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("result"), str):
                for nested in JobRunner._candidate_json_strings(parsed["result"]):
                    try:
                        nested_parsed = json.loads(nested)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(nested_parsed, dict):
                        return nested_parsed
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _candidate_json_strings(raw: str) -> list[str]:
        candidates = [raw.strip()]
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S)
        if fence_match:
            candidates.append(fence_match.group(1).strip())
        extracted = JobRunner._extract_first_json_object(raw)
        if extracted:
            candidates.append(extracted)
        unique: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item and item not in seen:
                unique.append(item)
                seen.add(item)
        return unique

    @staticmethod
    def _extract_first_json_object(raw: str) -> str | None:
        start = raw.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for idx in range(start, len(raw)):
                char = raw[idx]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return raw[start : idx + 1]
            start = raw.find("{", start + 1)
        return None


class JobExecutor:
    def __init__(self, store: JobStore, runtime: Runtime, config: Settings) -> None:
        self.store = store
        self.runtime = runtime
        self.config = config
        self.workflow = PaperWorkflow(runtime)

    def _log(self, job_id: int, stage: str, message: str, *, level: str = "INFO") -> None:
        timestamp = now_iso()
        self.store.append_log(
            job_id=job_id,
            created_at=timestamp,
            level=level,
            stage=stage,
            message=message,
        )
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.config.logs_dir / f"{job_id}.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} [{level}] ({stage}) {message}\n")

    def _update(self, job_id: int, **kwargs: Any) -> None:
        self.store.set_status(job_id, updated_at=now_iso(), **kwargs)

    def _artifact_dir(self, job_id: int) -> Path:
        return self.runtime.artifact_dir(job_id)

    @staticmethod
    def _is_git_blocker(message: str) -> bool:
        lowered = message.lower()
        blockers = (
            "could not resolve hostname",
            "could not read from remote repository",
            "connection timed out",
            "operation timed out",
            "network is unreachable",
            "connection reset",
            "failed to connect",
            "command timed out",
            "couldn't connect to server",
        )
        return any(token in lowered for token in blockers)

    def _stdout_logger(self, job_id: int):
        def callback(line: str) -> None:
            if line.strip():
                self._log(job_id, "agent_stdout", line)
        return callback

    def _stderr_logger(self, job_id: int):
        def callback(line: str) -> None:
            if line.strip():
                self._log(job_id, "agent_stderr", line, level="WARN")
        return callback

    def run(self, job_id: int) -> int:
        job = self.store.get_job(job_id)
        if not job:
            return 1
        artifact_dir = self._artifact_dir(job_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self.store.attach_worker_pid(job_id, os.getpid(), now_iso())
        self._update(job_id, artifact_dir=str(artifact_dir), worker_pid=os.getpid(), stage="preflight", status="running")

        auth_ok, auth_message = self.runtime.auth_check(force=True)
        if not auth_ok:
            self._log(job_id, "waiting_auth", auth_message, level="WARN")
            self._update(
                job_id,
                status="waiting_auth",
                stage="waiting_auth",
                error_message=auth_message,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 0

        if not (self.config.obsidian_sync_repo / ".git").exists():
            message = f"git repo missing: {self.config.obsidian_sync_repo}"
            self._log(job_id, "blocked_git", message, level="WARN")
            self._update(
                job_id,
                status="blocked_git",
                stage="blocked_git",
                error_message=message,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 0

        def workflow_log(stage: str, message: str, level: str = "INFO") -> None:
            self._log(job_id, stage, message, level=level)
            self._update(
                job_id,
                status="running",
                stage=stage,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )

        def set_notebook(notebook_id: str, notebook_title: str) -> None:
            self.store.set_notebook(job_id, notebook_id, notebook_title, now_iso())
            job["notebook_id"] = notebook_id
            job["notebook_title"] = notebook_title

        def set_paper_title(paper_title: str) -> None:
            if not paper_title:
                return
            self._update(
                job_id,
                status="running",
                stage=job.get("stage") or "routing",
                paper_title=paper_title,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            job["paper_title"] = paper_title

        def set_source_fingerprint(source_fingerprint: str) -> None:
            if not source_fingerprint:
                return
            self.store.set_source_fingerprint(job_id, source_fingerprint, now_iso())
            job["source_fingerprint"] = source_fingerprint

        try:
            result = self.workflow.execute(job, workflow_log, set_notebook=set_notebook, set_paper_title=set_paper_title)
            set_source_fingerprint(result.source_fingerprint)
        except Exception as exc:
            error_message = str(exc) or "paper workflow failed"
            self.runtime.write_artifact(job_id, "failure.txt", error_message)
            if self._is_git_blocker(error_message):
                self._update(
                    job_id,
                    status="blocked_git",
                    stage="blocked_git",
                    error_message=error_message,
                    worker_pid=os.getpid(),
                    artifact_dir=str(artifact_dir),
                )
                self._log(job_id, "blocked_git", error_message, level="WARN")
                return 0
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error_message=error_message,
                finished_at=now_iso(),
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            self._log(job_id, "failed", error_message, level="WARN")
            return 1

        self.runtime.write_artifact(
            job_id,
            "parsed_result.json",
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
        )
        self._update(
            job_id,
            status="completed",
            stage="completed",
            paper_title=result.paper_title or None,
            canonical_paper_key=result.canonical_paper_key or None,
            framework_version=result.framework_version or self.config.framework_version,
            source_fingerprint=result.source_fingerprint or None,
            metadata_complete=1,
            output_path=result.output_path or None,
            result_summary=result.summary or None,
            finished_at=now_iso(),
            worker_pid=os.getpid(),
            artifact_dir=str(artifact_dir),
        )
        self._log(job_id, "completed", result.output_path or "completed")
        return 0


store = JobStore(settings.db_path)
runtime = Runtime(settings)
runner = JobRunner(store, runtime, settings)
