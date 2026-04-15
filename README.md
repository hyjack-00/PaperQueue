# Paper Reading Queue

Minimal host-side queue service for running the `notebooklm-paper-reader` Claude skill and writing notes into the Nextcloud-backed `MAIN` vault.

## Run

```bash
bash scripts/setup_host.sh
uvicorn run_server:app --host 0.0.0.0 --port 8000
```

## Notes

- The service expects `claude`, `nlm`, `docker-compose`, `jinja2`, `starlette`, and `uvicorn` to already exist on the host.
- Queue jobs call:
  `CLAUDE_CONFIG_DIR=/home/agent-user/.claude-glm claude --dangerously-skip-permissions`
- Notes are written under:
  `/workspace/nextcloud/data/data/admin/files/MAIN/paper/<notebook>/`
