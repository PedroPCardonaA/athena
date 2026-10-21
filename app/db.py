import hashlib
import os
import sqlite3

DB_PATH = os.environ.get("IDEAS_DB", "data/ideas.db")

STATUSES = ("seed", "exploring", "active", "parked", "dropped")
KINDS = ("paper", "repo", "blog", "dataset", "other")
NOTE_KINDS = ("user", "agent_report")

MIGRATIONS = [
"""
CREATE TABLE ideas(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  body_md TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'seed',
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE sources(
  id INTEGER PRIMARY KEY,
  idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  authors TEXT NOT NULL DEFAULT '',
  year INTEGER,
  kind TEXT NOT NULL DEFAULT 'other',
  note TEXT NOT NULL DEFAULT '',
  added_by TEXT NOT NULL DEFAULT 'user',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(idea_id, url)
);
CREATE TABLE notes(
  id INTEGER PRIMARY KEY,
  idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'user',
  body_md TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE api_tokens(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  hash TEXT NOT NULL UNIQUE,
  scope TEXT NOT NULL CHECK(scope IN ('read','write')),
  last_used TEXT
);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIRTUAL TABLE fts USING fts5(title, summary, body_md, tags);
""",
"""
CREATE INDEX notes_idea ON notes(idea_id, created_at);
CREATE INDEX ideas_updated ON ideas(updated_at);
""",
]


def connect(path=None):
    path = path or DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for n, script in enumerate(MIGRATIONS[version:], start=version + 1):
        con.executescript(script)
        con.execute(f"PRAGMA user_version={n}")
        con.commit()
    return con


def hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _reindex(con, idea_id):
    r = con.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    con.execute("DELETE FROM fts WHERE rowid=?", (idea_id,))
    if r:
        con.execute(
            "INSERT INTO fts(rowid,title,summary,body_md,tags) VALUES(?,?,?,?,?)",
            (idea_id, r["title"], r["summary"], r["body_md"], r["tags"]),
        )


def create_idea(con, title, summary="", body_md="", status="seed", tags=""):
    cur = con.execute(
        "INSERT INTO ideas(title,summary,body_md,status,tags) VALUES(?,?,?,?,?)",
        (title, summary, body_md, status, tags),
    )
    _reindex(con, cur.lastrowid)
    con.commit()
    return cur.lastrowid


def update_idea(con, idea_id, **fields):
    allowed = {"title", "summary", "body_md", "status", "tags"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    con.execute(
        f"UPDATE ideas SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (*fields.values(), idea_id),
    )
    _reindex(con, idea_id)
    con.commit()


def delete_idea(con, idea_id):
    con.execute("DELETE FROM fts WHERE rowid=?", (idea_id,))
    con.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
    con.commit()


def list_ideas(con, q="", status=""):
    sql, args = "SELECT * FROM ideas", []
    where = []
    if q.strip():
        # quote each term so user input can't inject FTS syntax
        terms = " ".join('"%s"' % t.replace('"', "") for t in q.split() if t.replace('"', ""))
        if terms:
            where.append("id IN (SELECT rowid FROM fts WHERE fts MATCH ?)")
            args.append(terms)
    if status:
        where.append("status=?")
        args.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return con.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()


def get_idea(con, idea_id):
    return con.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()


def sources_of(con, idea_id):
    return con.execute(
        "SELECT * FROM sources WHERE idea_id=? ORDER BY created_at DESC, id DESC", (idea_id,)
    ).fetchall()


def notes_of(con, idea_id):
    return con.execute(
        "SELECT * FROM notes WHERE idea_id=? ORDER BY created_at DESC, id DESC", (idea_id,)
    ).fetchall()


def add_source(con, idea_id, url, title="", authors="", year=None, kind="other", note="", added_by="user"):
    """Returns (id, created). Existing url for the idea is left untouched."""
    cur = con.execute(
        "INSERT OR IGNORE INTO sources(idea_id,url,title,authors,year,kind,note,added_by) VALUES(?,?,?,?,?,?,?,?)",
        (idea_id, url, title, authors, year, kind, note, added_by),
    )
    if cur.rowcount:
        con.execute("UPDATE ideas SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (idea_id,))
    con.commit()
    if cur.rowcount:
        return cur.lastrowid, True
    row = con.execute("SELECT id FROM sources WHERE idea_id=? AND url=?", (idea_id, url)).fetchone()
    return row["id"], False


def add_note(con, idea_id, body_md, kind="user"):
    cur = con.execute("INSERT INTO notes(idea_id,kind,body_md) VALUES(?,?,?)", (idea_id, kind, body_md))
    con.execute("UPDATE ideas SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (idea_id,))
    con.commit()
    return cur.lastrowid


EXPORT_VERSION = 1


def export_all(con):
    ideas = []
    for i in con.execute("SELECT * FROM ideas ORDER BY id"):
        d = {k: i[k] for k in ("title", "summary", "body_md", "status", "tags", "created_at", "updated_at")}
        d["sources"] = [
            {k: r[k] for k in ("url", "title", "authors", "year", "kind", "note", "added_by", "created_at")}
            for r in con.execute("SELECT * FROM sources WHERE idea_id=? ORDER BY id", (i["id"],))
        ]
        d["notes"] = [
            {k: r[k] for k in ("kind", "body_md", "created_at")}
            for r in con.execute("SELECT * FROM notes WHERE idea_id=? ORDER BY id", (i["id"],))
        ]
        ideas.append(d)
    return {"version": EXPORT_VERSION, "ideas": ideas}


def import_all(con, data):
    """Import validated export data in one transaction. Ideas matching an existing
    (title, created_at) are skipped. Returns (ideas_added, ideas_skipped)."""
    added = skipped = 0
    try:
        for d in data["ideas"]:
            if con.execute("SELECT 1 FROM ideas WHERE title=? AND created_at=?", (d["title"], d["created_at"])).fetchone():
                skipped += 1
                continue
            cur = con.execute(
                "INSERT INTO ideas(title,summary,body_md,status,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (d["title"], d["summary"], d["body_md"], d["status"], d["tags"], d["created_at"], d["updated_at"]),
            )
            iid = cur.lastrowid
            for r in d["sources"]:
                con.execute(
                    "INSERT OR IGNORE INTO sources(idea_id,url,title,authors,year,kind,note,added_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (iid, r["url"], r["title"], r["authors"], r["year"], r["kind"], r["note"], r["added_by"], r["created_at"]),
                )
            for r in d["notes"]:
                con.execute("INSERT INTO notes(idea_id,kind,body_md,created_at) VALUES(?,?,?,?)", (iid, r["kind"], r["body_md"], r["created_at"]))
            _reindex(con, iid)
            added += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return added, skipped
