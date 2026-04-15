from __future__ import annotations

import argparse
import json
import sys
import time

from .runtime import JobExecutor, now_iso, runtime, settings, store


def _create_job(input_text: str, notebook_id: str, notebook_title: str) -> int:
    return store.create_job(
        input_text=input_text.strip(),
        notebook_id=notebook_id.strip(),
        notebook_title=notebook_title.strip(),
        created_at=now_iso(),
    )


def _job_payload(job_id: int) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise SystemExit(f"job not found: {job_id}")
    job["recent_logs"] = store.get_recent_logs(job_id, 20)
    return job


def cmd_submit(args: argparse.Namespace) -> int:
    job_id = _create_job(args.input, args.notebook_id, args.notebook_title)
    print(job_id)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(_job_payload(args.job_id), ensure_ascii=False, indent=2))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    offset = 0
    while True:
        text = store.get_log_text(args.job_id)
        lines = text.splitlines()
        for line in lines[offset:]:
            print(line)
        offset = len(lines)
        if not args.follow:
            return 0
        job = store.get_job(args.job_id)
        if not job or job["status"] in {"completed", "failed"}:
            return 0
        time.sleep(2)


def cmd_wait(args: argparse.Namespace) -> int:
    while True:
        job = _job_payload(args.job_id)
        print(
            json.dumps(
                {
                    "id": job["id"],
                    "status": job["status"],
                    "stage": job["stage"],
                    "paper_title": job.get("paper_title"),
                    "output_path": job.get("output_path"),
                    "error_message": job.get("error_message"),
                },
                ensure_ascii=False,
            )
        )
        if job["status"] in {"completed", "failed", "waiting_auth", "blocked_nextcloud"}:
            return 0 if job["status"] == "completed" else 1
        time.sleep(3)


def cmd_run(args: argparse.Namespace) -> int:
    job_id = _create_job(args.input, args.notebook_id, args.notebook_title)
    claimed = store.claim_job_by_id(job_id, now_iso())
    if not claimed:
        print(f"failed to claim job {job_id}", file=sys.stderr)
        return 1
    code = JobExecutor(store, runtime, settings).run(job_id)
    print(json.dumps(_job_payload(job_id), ensure_ascii=False, indent=2))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m paper_queue.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--input", required=True)
    submit.add_argument("--notebook-id", required=True)
    submit.add_argument("--notebook-title", required=True)
    submit.set_defaults(func=cmd_submit)

    status = sub.add_parser("status")
    status.add_argument("job_id", type=int)
    status.set_defaults(func=cmd_status)

    logs = sub.add_parser("logs")
    logs.add_argument("job_id", type=int)
    logs.add_argument("--follow", action="store_true")
    logs.set_defaults(func=cmd_logs)

    wait = sub.add_parser("wait")
    wait.add_argument("job_id", type=int)
    wait.set_defaults(func=cmd_wait)

    run = sub.add_parser("run")
    run.add_argument("--input", required=True)
    run.add_argument("--notebook-id", required=True)
    run.add_argument("--notebook-title", required=True)
    run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
