# Ideas Saver

Small self-hosted vault for PhD/research ideas and their sources (FastAPI + SQLite, no JS, no build step), plus a Claude Code skill that researches an idea and writes results back.

## Run
```
cp .env.example .env && chmod 600 .env   # set IDEAS_ADMIN_PASSWORD (>=12 chars, used on first run only)
podman-compose up -d --build              # http://127.0.0.1:8787  (localhost only)
```
Container: rootless, read-only rootfs, all caps dropped, no-new-privileges, non-root user. Data lives in `./data/ideas.db`.

## Agent skill
1. UI → *API tokens* → create a `write` token.
2. `mkdir -p ~/.config/ideas-saver && echo '{"url":"http://127.0.0.1:8787","token":"ids_..."}' > ~/.config/ideas-saver/config && chmod 600 ~/.config/ideas-saver/config`
3. `cp -r skill/research-idea ~/.claude/skills/`
4. In Claude Code: "research idea 3".

## Backup
`sqlite3 data/ideas.db ".backup data/backup-$(date +%F).db"`

## Tests
`pip install -r requirements.txt pytest httpx && pytest`
