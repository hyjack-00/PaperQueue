# Paper Reading Queue

Minimal host-side queue service for generating NotebookLM paper notes and syncing them into the Git-backed Obsidian repo at `/workspace/obsidian_sync`.

## Run

```bash
bash scripts/setup_host.sh
uvicorn run_server:app --host 0.0.0.0 --port 8000
```

## Notes

- The service expects `claude`, `nlm`, `jinja2`, `starlette`, and `uvicorn` to already exist on the host.
- Notes are written under:
  `/workspace/obsidian_sync/paper/<canonical-taxonomy-topic>/`
- The queue syncs against `origin/main` before writing, then commits and pushes the new note.
