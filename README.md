<p align="center"><img src="docs/logo.png" alt="Athena owl" width="120"></p>

# Athena

A tiny, private vault for your PhD/research ideas, the sources behind each idea, and a journal, plus an agent hook that researches an idea for you (state of the art, related work, gaps) and files the results.

- **Organised**: group ideas into projects; status, tags, full-text search; a ChatGPT/Claude-style sidebar UI with light and dark themes.
- **Local and single-user**: runs in a rootless podman container, bound to `127.0.0.1`. Your data is one SQLite file in `./data`.
- **Simple**: FastAPI + SQLite, server-rendered, no JavaScript, no build step, 8 small dependencies.
- **Secure by default**: read-only container, no capabilities, argon2 password, CSRF, strict CSP. See [SECURITY.md](SECURITY.md).
- **Yours**: full JSON export/import, BibTeX export/import, `make backup`.
- **Agent-friendly**: scoped HTTP API ([docs/api.md](docs/api.md)), works with any agent ([AGENTS.md](AGENTS.md)); a Claude Code skill is included.

## Quickstart
Requires `podman` and `podman-compose`.
```bash
git clone https://github.com/PedroPCardonaA/athena && cd athena
./setup.sh
```
Open http://127.0.0.1:8787 and choose a password (first run only). `setup.sh` can also install the research skill.

Manual: `make up` (uses the prebuilt image `ghcr.io/pedropcardonaa/athena`). Optionally set `ATHENA_ADMIN_PASSWORD` in the environment to skip the setup page.

## Research with an agent
1. UI → **Settings → Agent access** → create a `write` token.
2. Put it in `~/.config/athena/config` (`setup.sh` does this), install `skill/research-idea` into `~/.claude/skills/`.
3. Tell your agent: *"research idea 3"*. It searches, adds sources with relevance notes, and saves a structured report. Agent-added items are labelled in the UI.

## Your data
| Task | How |
|---|---|
| Backup (consistent) | `make backup` → `data/backups/` |
| Restore | stop the app, `make restore FILE=data/backups/<file>.db`, start |
| Move/share ideas | UI → **Settings → Agent access** page → *Export* / *Import* (JSON) |
| Citations | idea page → BibTeX → download `.bib` or paste entries to import |
| Upgrade | `podman-compose pull && podman-compose up -d` (schema migrates automatically; back up first) |

## Develop
See [CONTRIBUTING.md](CONTRIBUTING.md). `make test`, `make dev`.

## License
MIT
