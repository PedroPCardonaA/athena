<p align="center"><img src="docs/logo.png" alt="Athena owl" width="120"></p>

# Athena

A tiny, private vault for your PhD/research ideas, the sources behind each idea, and a journal, plus an agent hook that researches an idea for you (state of the art, related work, gaps) and files the results.

- **Organised**: group ideas into projects; status, tags, full-text search; a ChatGPT/Claude-style sidebar UI with light and dark themes.
- **Local and single-user**: runs in a rootless podman container, bound to `127.0.0.1`. Your data is one SQLite file in `./data`.
- **Simple**: FastAPI + SQLite, server-rendered, no JavaScript, no build step, a handful of dependencies.
- **Secure by default**: read-only container, no capabilities, argon2 password, CSRF, strict CSP. See [SECURITY.md](SECURITY.md).
- **Yours**: full JSON export/import, BibTeX export/import, `make backup`.
- **Agent-friendly**: a full MCP server (read, add, change; summarize and improve prompts) that installs with one command ([docs/mcp.md](docs/mcp.md), [AGENTS.md](AGENTS.md)).
- **Citations everywhere**: sources per idea and per project; a project page rolls them all up with clickable links, BibTeX in/out. Upload local `.md`/`.txt`/`.pdf` documents as sources (stored in `data/docs`).
- **Agent history**: the **History** page lists everything an agent added or changed through MCP, filterable by action and type.

## Quickstart
Requires `podman` and `podman-compose`.
```bash
git clone https://github.com/PedroPCardonaA/athena && cd athena
./setup.sh
```
Open http://127.0.0.1:8787 and choose a password (first run only). `setup.sh` can also connect your AI agent.

Manual: `make up` (uses the prebuilt image `ghcr.io/pedropcardonaa/athena`). Optionally set `ATHENA_ADMIN_PASSWORD` in the environment to skip the setup page.

> **Upgrading from v0.2?** v0.3 removes the REST API and API tokens in favour of MCP. Back up first (`make backup`); the migration drops the token table. Re-add your agent with the command below.

## Connect an AI agent (MCP)
No tokens, no open ports. With Athena running:
```bash
claude mcp add athena -- podman exec -i athena python -m app.athena_mcp
```
(also Codex, Cursor, Windsurf, Gemini CLI, Claude Desktop: see [docs/mcp.md](docs/mcp.md); add `--read-only` for view-only access.)
Then ask your agent things like *"summarize my PhD Thesis project"*, *"research idea 3"* or *"add these papers to the project"*. It can read, add and change projects, ideas, sources and notes (never delete), and ships ready-made prompts: `summarize_project`, `improve_idea`, `research_idea`, `find_related_work`, `weekly_review`.

## Your data
| Task | How |
|---|---|
| Backup (consistent) | `make backup` → `data/backups/` |
| Restore | stop the app, `make restore FILE=data/backups/<file>.db`, start |
| Move/share ideas | UI → **Settings → Agent access** page → *Export* / *Import* (JSON) |
| Local documents | uploaded files live in `data/docs/`; `make backup` copies only the database, so back up that folder too |
| Citations | idea page → BibTeX → download `.bib` or paste entries to import |
| Upgrade | `podman-compose pull && podman-compose up -d` (schema migrates automatically; back up first) |

## Develop
See [CONTRIBUTING.md](CONTRIBUTING.md). `make test`, `make dev`.

## License
MIT
