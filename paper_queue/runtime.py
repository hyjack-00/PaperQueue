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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings, settings
from .db import JobStore


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
        self._cache_lock = threading.Lock()
        self._auth_cache: tuple[float, bool, str] | None = None
        self._notebook_cache: tuple[float, list[dict[str, str]], str | None] | None = None

    def run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = 120.0,
    ) -> CommandResult:
        try:
            proc = subprocess.run(
                args,
                text=True,
                capture_output=True,
                env=env,
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

    def system_status(self) -> dict[str, Any]:
        auth_ok, auth_message = self.auth_check()
        nextcloud_ok, nextcloud_message = self.nextcloud_check()
        skill_ok = (self.config.skill_install_path / "SKILL.md").exists()
        paper_root_exists = self._path_exists(self.config.paper_root)
        paper_root_writable = self._path_writable(self.config.paper_root)
        return {
            "auth_ok": auth_ok,
            "auth_message": auth_message,
            "claude_ok": shutil.which("claude") is not None,
            "nlm_ok": shutil.which("nlm") is not None,
            "skill_ok": skill_ok,
            "skill_path": str(self.config.skill_install_path),
            "nextcloud_ok": nextcloud_ok,
            "nextcloud_message": nextcloud_message,
            "paper_root": str(self.config.paper_root),
            "paper_root_exists": paper_root_exists,
            "paper_root_writable": paper_root_writable,
        }

    def nextcloud_check(self) -> tuple[bool, str]:
        compose_cmd = [
            "docker-compose",
            "-f",
            str(self.config.nextcloud_compose_file),
            "ps",
            "-q",
            "nextcloud",
        ]
        result = self.run(compose_cmd, timeout=15.0)
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "nextcloud check failed"
            return False, message
        if not result.stdout.strip():
            return False, "nextcloud not running"
        return True, "nextcloud running"

    def _path_exists(self, path: Path) -> bool:
        try:
            return path.exists()
        except PermissionError:
            result = self.run(["sudo", "-n", "test", "-d", str(path)])
            return result.ok

    def _path_writable(self, path: Path) -> bool:
        if os.access(path, os.W_OK):
            return True
        result = self.run(["sudo", "-n", "test", "-w", str(path)])
        return result.ok

    def normalize_output_permissions(self, output_path: str) -> CommandResult:
        path = Path(output_path)
        parent = path.parent
        command = (
            f"sudo -n chown -R www-data:www-data {shlex.quote(str(parent))} && "
            f"sudo -n find {shlex.quote(str(parent))} -type d -exec chmod 2775 {{}} + && "
            f"sudo -n find {shlex.quote(str(parent))} -type f -exec chmod 664 {{}} +"
        )
        return self.run_shell(command)

    def build_agent_prompt(self, *, job: dict[str, Any]) -> str:
        skill_path = self.config.skill_install_path / "SKILL.md"
        source_skill_path = self.config.skill_source_dir / "SKILL.md"
        output_dir = self.config.paper_root / job["notebook_title"]
        return f"""
You are handling a queued paper-reading job on the host machine.

Use the installed Claude skill named /{self.config.skill_name}. If it is unavailable in runtime,
immediately read this fallback skill file and follow it exactly:
{source_skill_path}

Job input:
- raw_input: {job["input_text"]}
- notebook_id: {job["notebook_id"]}
- notebook_title: {job["notebook_title"]}

Execution rules:
1. This is non-interactive queue mode. Do not ask follow-up questions.
2. If NotebookLM auth is invalid, stop and return JSON with status AUTH_REQUIRED.
3. Save the final markdown note directly to:
   {output_dir}
4. The Obsidian vault root is:
   {self.config.paper_root.parent}
5. The target vault name is:
   {self.config.vault_root_name}
6. Use direct file writes, not Obsidian CLI.
7. If the target filename already exists, create -v2, -v3, etc.
8. After writing the file, run:
   docker-compose -f {self.config.nextcloud_compose_file} exec -T nextcloud php occ files:scan --path="/admin/files/{self.config.vault_root_name}/{self.config.paper_subdir}/{job["notebook_title"]}"
9. Reply with JSON only, no markdown fences, with this schema:
   {{
     "status": "completed" | "AUTH_REQUIRED" | "failed",
     "paper_title": string,
     "output_path": string,
     "summary": string,
     "error": string
   }}
"""

    def run_claude_job(self, job: dict[str, Any]) -> CommandResult:
        prompt = self.build_agent_prompt(job=job)
        command = (
            f"{self.config.claude_glm_command} "
            f"-p --output-format json --model {shlex.quote(self.config.claude_model)} "
            f"{shlex.quote(prompt)}"
        )
        artifact_dir = self.artifact_dir(int(job["id"]))
        return self.run_shell_streaming(
            command,
            cwd=self.config.skill_source_dir.parent,
            timeout=self.config.agent_timeout_seconds,
            artifact_dir=artifact_dir,
        )

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
        self._last_nextcloud_check = 0.0

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
            self._maybe_requeue_blocked_nextcloud()
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

    def _maybe_requeue_blocked_nextcloud(self) -> None:
        now = time.monotonic()
        if now - self._last_nextcloud_check < self.config.nextcloud_recheck_seconds:
            return
        self._last_nextcloud_check = now
        jobs = self.store.list_jobs()
        if not any(job["status"] == "blocked_nextcloud" for job in jobs):
            return
        nextcloud_ok, _ = self.runtime.nextcloud_check()
        if nextcloud_ok:
            self.store.requeue_blocked_nextcloud(now_iso())

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

        nextcloud_ok, nextcloud_message = self.runtime.nextcloud_check()
        if not nextcloud_ok:
            self._log(job_id, "blocked_nextcloud", nextcloud_message, level="WARN")
            self._update(
                job_id,
                status="blocked_nextcloud",
                stage="blocked_nextcloud",
                error_message=nextcloud_message,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 0

        if not self.runtime._path_exists(self.config.paper_root):
            message = f"paper root missing: {self.config.paper_root}"
            self._log(job_id, "blocked_nextcloud", message, level="WARN")
            self._update(
                job_id,
                status="blocked_nextcloud",
                stage="blocked_nextcloud",
                error_message=message,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 0

        self._log(job_id, "agent", "Invoking claude-glm workflow")
        prompt = self.runtime.build_agent_prompt(job=job)
        self.runtime.write_artifact(job_id, "prompt.txt", prompt)
        command = (
            f"{self.config.claude_glm_command} "
            f"-p --output-format json --model {shlex.quote(self.config.claude_model)} "
            f"{shlex.quote(prompt)}"
        )
        result = self.runtime.run_shell_streaming(
            command,
            cwd=self.config.skill_source_dir.parent,
            timeout=self.config.agent_timeout_seconds,
            log_stdout=self._stdout_logger(job_id),
            log_stderr=self._stderr_logger(job_id),
            artifact_dir=artifact_dir,
        )
        self._log(job_id, "agent", f"Command exit code: {result.returncode}")

        if not result.ok:
            error_message = (result.stderr or result.stdout).strip() or "claude-glm failed"
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error_message=error_message,
                finished_at=now_iso(),
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 1

        parsed = JobRunner._parse_claude_output(result.stdout)
        if parsed is None:
            self.runtime.write_artifact(job_id, "parse_error.txt", result.stdout)
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error_message="Could not parse claude-glm result JSON",
                finished_at=now_iso(),
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 1
        self.runtime.write_artifact(job_id, "parsed_result.json", json.dumps(parsed, ensure_ascii=False, indent=2))

        status = parsed.get("status")
        if status == "AUTH_REQUIRED":
            message = str(parsed.get("error") or "NotebookLM auth required")
            self._log(job_id, "waiting_auth", message, level="WARN")
            self._update(
                job_id,
                status="waiting_auth",
                stage="waiting_auth",
                error_message=message,
                paper_title=str(parsed.get("paper_title") or "") or None,
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 0
        if status != "completed":
            message = str(parsed.get("error") or "Paper workflow failed")
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error_message=message,
                paper_title=str(parsed.get("paper_title") or "") or None,
                finished_at=now_iso(),
                worker_pid=os.getpid(),
                artifact_dir=str(artifact_dir),
            )
            return 1

        self._update(
            job_id,
            status="completed",
            stage="completed",
            paper_title=str(parsed.get("paper_title") or "") or None,
            output_path=str(parsed.get("output_path") or "") or None,
            result_summary=str(parsed.get("summary") or "") or None,
            finished_at=now_iso(),
            worker_pid=os.getpid(),
            artifact_dir=str(artifact_dir),
        )
        output_path = str(parsed.get("output_path") or "")
        if output_path:
            perm_result = self.runtime.normalize_output_permissions(output_path)
            if perm_result.ok:
                self._log(job_id, "permissions", "Normalized ownership to www-data")
            else:
                self._log(
                    job_id,
                    "permissions",
                    (perm_result.stderr or perm_result.stdout).strip() or "permission normalization failed",
                    level="WARN",
                )
        self._log(job_id, "completed", str(parsed.get("output_path") or "completed"))
        return 0


store = JobStore(settings.db_path)
runtime = Runtime(settings)
runner = JobRunner(store, runtime, settings)
