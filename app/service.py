"""Domain operations shared by the web UI and the MCP server, so rules live in one place."""
from urllib.parse import urlparse

from . import db

MAX_BATCH = 50


def safe_url(url: str) -> str:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("url must be http(s)")
    return url.strip()


def domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host.removeprefix("www.")


def add_source(con, *, idea_id=None, project_id=None, url, title="", authors="", year=None,
               kind="other", note="", added_by="user"):
    """Add a source to exactly one idea or one project. Returns (id, created)."""
    if (idea_id is None) == (project_id is None):
        raise ValueError("give exactly one of idea_id or project_id")
    fields = dict(url=safe_url(url), title=title, authors=authors, year=year, kind=kind, note=note, added_by=added_by)
    if idea_id is not None:
        if not db.get_idea(con, idea_id):
            raise LookupError(f"idea {idea_id} not found")
        return db.add_source(con, idea_id, **fields)
    if not db.get_project(con, project_id):
        raise LookupError(f"project {project_id} not found")
    return db.add_project_source(con, project_id, **fields)


def rollup(con, project_id):
    """One row per URL across the project's own sources and its ideas' sources."""
    rows = {}

    def merge(r, direct, idea=None):
        e = rows.setdefault(r["url"], {
            "url": r["url"], "title": "", "authors": "", "year": None, "kind": r["kind"], "note": "",
            "direct": False, "agent": False, "cited_by": [], "created_at": r["created_at"]})
        for k in ("title", "authors", "note"):  # keep the most informative (longest) value
            if len(r[k] or "") > len(e[k]):
                e[k] = r[k]
        if e["year"] is None:
            e["year"] = r["year"]
        if e["kind"] == "other":
            e["kind"] = r["kind"]
        e["direct"] |= direct
        e["agent"] |= r["added_by"] == "agent"
        e["created_at"] = max(e["created_at"], r["created_at"])
        if idea and idea not in e["cited_by"]:
            e["cited_by"].append(idea)

    for r in db.project_sources_of(con, project_id):
        merge(r, True)
    for r in con.execute(
        "SELECT s.*, i.id AS iid, i.title AS ititle FROM sources s JOIN ideas i ON i.id=s.idea_id "
        "WHERE i.project_id=? ORDER BY s.created_at DESC, s.id DESC", (project_id,)):
        merge(r, False, {"id": r["iid"], "title": r["ititle"]})
    out = sorted(rows.values(), key=lambda e: e["created_at"], reverse=True)
    for e in out:
        e["domain"] = domain(e["url"])
    return out


def search(con, q, limit=20):
    """Case-insensitive search over ideas (full text), sources and notes."""
    q = (q or "").strip()[:200]
    if not q:
        return {"ideas": [], "sources": [], "notes": []}
    ideas = [dict(r) for r in db.list_ideas(con, q)][:limit]
    like = "instr(lower({}), lower(?)) > 0"
    src_cols = ("url", "title", "authors", "note")
    cond = " OR ".join(like.format(c) for c in src_cols)
    args = [q] * len(src_cols)
    sources = [dict(r, scope="idea") for r in con.execute(
        f"SELECT id, idea_id, NULL AS project_id, url, title, authors, year, kind, note FROM sources WHERE {cond} LIMIT ?",
        (*args, limit))]
    sources += [dict(r, scope="project") for r in con.execute(
        f"SELECT id, NULL AS idea_id, project_id, url, title, authors, year, kind, note FROM project_sources WHERE {cond} LIMIT ?",
        (*args, limit))]
    notes = [dict(r) for r in con.execute(
        "SELECT id, idea_id, kind, substr(body_md,1,300) AS excerpt FROM notes WHERE instr(lower(body_md), lower(?)) > 0 LIMIT ?",
        (q, limit))]
    return {"ideas": ideas, "sources": sources[:limit], "notes": notes}


def _clip(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def digest(con, project_id, max_chars=12000):
    """Compact markdown view of a project, sized for an agent to summarise."""
    p = db.get_project(con, project_id)
    if not p:
        raise LookupError(f"project {project_id} not found")
    ideas = db.list_ideas(con, project_id=project_id)
    out = [f"# Project: {p['name']} (id {p['id']})"]
    if p["description"]:
        out.append(p["description"])
    out.append("\n## Current summary\n" + (_clip(p["summary_md"], 3000) or "(none yet)"))
    out.append(f"\n## Ideas ({len(ideas)})")
    for i in ideas:
        out.append(f"\n### [{i['id']}] {i['title']} — {i['status']}" + (f" — tags: {i['tags']}" if i["tags"] else ""))
        if i["summary"]:
            out.append(_clip(i["summary"], 500))
        if i["body_md"]:
            out.append("Notes: " + _clip(i["body_md"], 700))
        rep = con.execute("SELECT body_md FROM notes WHERE idea_id=? AND kind='agent_report' ORDER BY id DESC LIMIT 1",
                          (i["id"],)).fetchone()
        if rep:
            out.append("Latest agent report: " + _clip(rep["body_md"], 500))
    srcs = rollup(con, project_id)
    out.append(f"\n## Sources ({len(srcs)})")
    for s in srcs:
        cites = ", ".join(f"[{c['id']}]" for c in s["cited_by"])
        out.append(f"- {s['title'] or s['url']}" + (f" ({s['year']})" if s["year"] else "") + f" <{s['url']}>"
                   + (f" — cited by ideas {cites}" if cites else " — project-level"))
    text = "\n".join(out)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n…(truncated)"
