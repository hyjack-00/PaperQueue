from __future__ import annotations

import sys

from .config import settings
from .runtime import JobExecutor, runtime, store


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m paper_queue.worker <job_id>", file=sys.stderr)
        return 2
    job_id = int(sys.argv[1])
    executor = JobExecutor(store, runtime, settings)
    return executor.run(job_id)


if __name__ == "__main__":
    raise SystemExit(main())
