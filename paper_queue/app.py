from __future__ import annotations

import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .config import settings
from .runtime import now_iso, runner, runtime, store


templates = Jinja2Templates(directory=str(settings.base_dir / "paper_queue" / "templates"))


def _asset_version() -> str:
    css = settings.base_dir / "paper_queue" / "static" / "style.css"
    js = settings.base_dir / "paper_queue" / "static" / "app.js"
    latest = max(css.stat().st_mtime_ns, js.stat().st_mtime_ns)
    return str(latest)


def _short_date(value: str | None) -> str:
    if not value:
        return "-"
    return value[:10]


def _display_title(job: dict) -> str:
    return str(job.get("paper_title") or job.get("input_text") or "-")


def _display_topic(job: dict) -> str:
    output_path = str(job.get("output_path") or "")
    parts = Path(output_path).parts
    if len(parts) >= 3 and parts[0] == settings.obsidian_sync_subdir:
        return str(parts[1])
    return str(job.get("notebook_title") or "Auto route")


def _canonical_job_key(job: dict) -> str:
    if job.get("canonical_paper_key"):
        return str(job["canonical_paper_key"])
    output_path = str(job.get("output_path") or "")
    if output_path:
        stem = re.sub(r"-v\d+$", "", Path(output_path).stem)
        if stem:
            return stem.lower()
    title = str(job.get("paper_title") or job.get("input_text") or "").strip().lower()
    return re.sub(r"\s+", " ", title)


def _annotate_latest(jobs: list[dict]) -> list[dict]:
    newest: dict[str, int] = {}
    for job in jobs:
        key = _canonical_job_key(job)
        if not key or job.get("status") != "completed":
            continue
        newest[key] = max(newest.get(key, 0), int(job["id"]))
    for job in jobs:
        key = _canonical_job_key(job)
        job["canonical_paper_key"] = key
        job["is_latest_version"] = bool(job.get("status") == "completed" and newest.get(key) == int(job["id"]))
    return jobs


def _serialize_jobs() -> list[dict]:
    jobs = _annotate_latest(store.system_snapshot(settings.recent_log_lines))
    for job in jobs:
        job["display_title"] = _display_title(job)
        job["display_topic"] = _display_topic(job)
        job["display_version"] = str(job.get("framework_version") or settings.framework_version)
        job["short_updated_at"] = _short_date(job.get("updated_at"))
    return jobs


def _serialize_job(job_id: int) -> dict | None:
    jobs = _serialize_jobs()
    return next((job for job in jobs if int(job["id"]) == int(job_id)), None)


async def homepage(request: Request) -> HTMLResponse:
    jobs = _serialize_jobs()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": settings.app_title,
            "jobs": jobs,
            "asset_version": _asset_version(),
        },
    )


async def job_detail(request: Request) -> HTMLResponse:
    job_id = int(request.path_params["job_id"])
    job = _serialize_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    job["short_created_at"] = _short_date(job.get("created_at"))
    job["short_updated_at"] = _short_date(job.get("updated_at"))
    logs = store.get_log_text(job_id)
    recent_logs = store.get_recent_logs(job_id, 40)
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "title": f"Job {job_id}",
            "job": job,
            "logs": logs,
            "recent_logs": recent_logs,
            "asset_version": _asset_version(),
            "framework_version": settings.framework_version,
        },
    )


def _extract_notebook(form: FormData) -> tuple[str, str]:
    notebook_id = str(form.get("notebook_id") or "").strip()
    notebook_title = str(form.get("notebook_title") or "").strip()
    if notebook_id and notebook_title:
        return notebook_id, notebook_title
    notebook = str(form.get("notebook") or "").strip()
    return notebook, notebook


async def submit_job(request: Request):
    form = await request.form()
    input_text = str(form.get("input") or "").strip()
    notebook_id, notebook_title = _extract_notebook(form)
    if not input_text:
        return JSONResponse({"error": "input is required"}, status_code=400)
    job_id = store.create_job(
        input_text=input_text,
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        created_at=now_iso(),
        framework_version=settings.framework_version,
    )
    return JSONResponse({"job_id": job_id})


async def api_jobs(_: Request) -> JSONResponse:
    return JSONResponse({"jobs": _serialize_jobs(), "active_job_id": runner.active_job_id})


async def api_job_detail(request: Request) -> JSONResponse:
    job_id = int(request.path_params["job_id"])
    job = _serialize_job(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    job["short_updated_at"] = _short_date(job.get("updated_at"))
    job["recent_logs"] = store.get_recent_logs(job_id, 40)
    return JSONResponse(job)


async def api_job_log(request: Request) -> PlainTextResponse:
    job_id = int(request.path_params["job_id"])
    return PlainTextResponse(store.get_log_text(job_id))


async def api_retry_job(request: Request) -> JSONResponse:
    job_id = int(request.path_params["job_id"])
    retried_job_id = store.retry_job(job_id, now_iso())
    if not retried_job_id:
        return JSONResponse({"error": "job is not retryable"}, status_code=400)
    store.append_log(
        job_id=retried_job_id,
        created_at=now_iso(),
        level="INFO",
        stage="queued",
        message="Job requeued by user",
    )
    return JSONResponse({"ok": True, "job_id": retried_job_id})


async def api_delete_job(request: Request) -> JSONResponse:
    job_id = int(request.path_params["job_id"])
    deleted = store.delete_job(job_id)
    if not deleted:
        return JSONResponse({"error": "not found"}, status_code=404)
    artifact_dir = deleted.get("artifact_dir")
    if artifact_dir:
        shutil.rmtree(artifact_dir, ignore_errors=True)
    log_path = settings.logs_dir / f"{job_id}.log"
    log_path.unlink(missing_ok=True)
    return JSONResponse({"ok": True})


async def api_notebooks(_: Request) -> JSONResponse:
    notebooks, error = runtime.notebook_list()
    if error:
        return JSONResponse({"error": error, "notebooks": []}, status_code=503)
    return JSONResponse({"notebooks": notebooks})


async def api_system_status(_: Request) -> JSONResponse:
    payload = runtime.system_status()
    payload["active_job_id"] = runner.active_job_id
    payload["queue_depth"] = len([job for job in store.list_jobs() if job["status"] == "queued"])
    return JSONResponse(payload)


routes = [
    Route("/", homepage),
    Route("/jobs/{job_id:int}", job_detail),
    Route("/submit", submit_job, methods=["POST"]),
    Route("/api/jobs", api_jobs),
    Route("/api/jobs/{job_id:int}", api_job_detail),
    Route("/api/jobs/{job_id:int}/log", api_job_log),
    Route("/api/jobs/{job_id:int}/retry", api_retry_job, methods=["POST"]),
    Route("/api/jobs/{job_id:int}/delete", api_delete_job, methods=["POST"]),
    Route("/api/notebooks", api_notebooks),
    Route("/api/system-status", api_system_status),
]

@asynccontextmanager
async def lifespan(_: Starlette):
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    runtime.install_skill()
    runner.start()
    try:
        yield
    finally:
        runner.stop()


app = Starlette(debug=False, routes=routes, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.base_dir / "paper_queue" / "static")), name="static")
