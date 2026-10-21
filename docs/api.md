# HTTP API

Base URL `http://127.0.0.1:8787`. Create a token in the UI (**Settings → Agent access**). Send `Authorization: Bearer ath_...`. Scopes: `read` (GET only) and `write` (GET, POST, PATCH). There are no delete endpoints. Errors: 401 bad/missing token, 403 read-only token, 404 unknown id, 422 invalid body.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/projects` | | list of projects with idea count `n` |
| POST | `/api/projects` | `{name, description?}` | `{id}` (201); 409 if the name exists |
| GET | `/api/ideas?q=&status=&project_id=` | `q` full-text, `status` one of seed, exploring, active, parked, dropped, `project_id` (`0` = unsorted) | list of ideas |
| POST | `/api/ideas` | `{title, summary?, body_md?, status?, tags?, project_id?}` | `{id}` (201) |
| GET | `/api/ideas/{id}` | | idea + `sources[]` + `notes[]` |
| PATCH | `/api/ideas/{id}` | any of title, summary, body_md, status, tags, project_id (`0` moves to Unsorted) | `{ok}` |
| POST | `/api/ideas/{id}/sources` | `{url (http/https), title?, authors?, year?, kind?, note?}` kind: paper, repo, blog, dataset, other | `{id, created}`; 201, or 200 if the URL already exists on the idea |
| POST | `/api/ideas/{id}/notes` | `{body_md, kind?}` kind: `agent_report` (default) or `user` | `{id}` (201) |
| GET | `/api/export` | | full export (same format as the UI's `/export.json`) |

```bash
T=ath_xxx
curl -s -H "Authorization: Bearer $T" 'http://127.0.0.1:8787/api/ideas?q=graph'
curl -s -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"url":"https://arxiv.org/abs/1706.03762","title":"Attention Is All You Need","kind":"paper","year":2017,"note":"baseline architecture"}' \
  http://127.0.0.1:8787/api/ideas/1/sources
```

Sources added through the API are marked `added_by: agent` in the UI.

## UI-only routes
`/export.json` (download everything), `POST /import` (restore an export; ideas with the same title and creation time are skipped), `/ideas/{id}/export.bib` (BibTeX), BibTeX import on an idea page, `/healthz`.
