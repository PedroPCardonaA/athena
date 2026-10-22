# Athena MCP server

Athena exposes your projects and ideas to AI agents through the [Model Context Protocol](https://modelcontextprotocol.io). There are **no tokens and no network port**: the agent starts a small process inside your local container with `podman exec`, so access is limited to whoever can already run commands in your container (you).

## Install

Start Athena first (`./setup.sh` or `make up`), then add the server to your agent:

| Client | Command |
|---|---|
| Claude Code | `claude mcp add athena -- podman exec -i athena python -m app.athena_mcp` |
| Claude Code (all projects) | `claude mcp add -s user athena -- podman exec -i athena python -m app.athena_mcp` |
| Codex | `codex mcp add athena -- podman exec -i athena python -m app.athena_mcp` |
| Cursor / Windsurf / Gemini CLI / Claude Desktop | add to the client's MCP JSON config (below) |

```json
{"mcpServers": {"athena": {"command": "podman",
  "args": ["exec", "-i", "athena", "python", "-m", "app.athena_mcp"]}}}
```

**Read-only mode:** append `--read-only` to the command (after `app.athena_mcp`). The write tools are then not offered at all.

Check it works: `claude mcp list` shows `athena ✓ Connected`, or ask your agent "list my Athena projects".

## Tools

Read (always available): `list_projects`, `get_project` (summary, ideas, own + rolled-up sources), `list_ideas` (query/status/project), `get_idea`, `search` (ideas, sources, notes), `get_project_digest` (compact text for summarising).

Write (hidden with `--read-only`): `create_project`, `update_project`, `set_project_summary`, `create_idea`, `update_idea` (partial; `project_id` moves it, `0` = Unsorted), `add_source` / `add_sources` (to an idea **or** a project; duplicates ignored; max 50 per batch), `add_note` (default kind `agent_report`).

Every successful write is recorded in the **History** page of the web UI (action add/update, entity type, tool, changed fields). Agents can only cite http(s) URLs; local documents are uploaded by you in the UI.

There are deliberately **no delete tools**; deleting stays a human action in the web UI. Agent-added sources and notes are labelled "agent" in the UI. Sources in `get_project`'s `all_sources` carry a `liked` flag (the researcher's ★ relevance marks); liking is a UI-only action, agents cannot change it.

## Resources
`athena://projects`, `athena://project/{id}` (digest), `athena://idea/{id}` (markdown).

## Prompts
Clients that support MCP prompts offer them as ready-made workflows (Claude Code: type `/mcp__athena__` and pick one):

| Prompt | What the agent does |
|---|---|
| `summarize_project(project_id)` | reads the digest, writes the project's Overview summary |
| `improve_idea(idea_id)` | critiques and sharpens an idea, saves feedback as an agent report (never overwrites your text) |
| `research_idea(idea_id)` | finds state of the art, related work and gaps on the web; adds verified sources + a report |
| `find_related_work(project_id)` | finds missing key references for the whole project |
| `weekly_review(project_id)` | reviews progress and proposes next actions (read-only) |

## Troubleshooting
- *"no container with name or ID athena"*: start the app (`make up`); the compose file names the container `athena`.
- Using plain `docker`? Replace `podman` with `docker` in the command.
- Server shows as failed: run `podman exec -i athena python -m app.athena_mcp --help` to see the error.
- Remove it: `claude mcp remove athena`.

## Security notes
Everything stored in Athena and everything an agent reads from the web is untrusted data; the server's instructions tell agents not to follow instructions found in it, but the real protection is: no delete tools, `--read-only` mode, size limits and URL validation on all inputs, and no agent-facing network surface. Any agent you connect **can edit** your ideas (use `--read-only` for agents you trust less).
