import os
import pytest
from fastapi.testclient import TestClient

os.environ["ATHENA_ADMIN_PASSWORD"] = "correct horse battery staple"
from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app.state.db_path = str(tmp_path / "t.db")
    auth._attempts.clear()
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/login", data={"password": "correct horse battery staple"}, follow_redirects=False)
    assert r.status_code == 303
    return auth.read_session(db.connect(app.state.db_path), c.cookies.get(auth.COOKIE))["csrf"]


def test_requires_login(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.post("/login", data={"password": "nope"}).status_code == 401


def test_csrf_and_xss(client):
    csrf = login(client)
    assert client.post("/ideas", data={"title": "x"}).status_code == 403
    r = client.post("/ideas", data={"title": "<script>alert(1)</script>", "csrf": csrf}, follow_redirects=True)
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    client.post("/ideas/1/notes", data={"body_md": "<img src=x onerror=alert(1)> [a](javascript:alert(1))", "csrf": csrf})
    t = client.get("/ideas/1").text
    assert "<img src=x" not in t and "onerror=" not in t.replace("&lt;img src=x onerror=", "") and 'href="javascript' not in t


def test_api_flow(client):
    csrf = login(client)
    wr = client.post("/tokens", data={"name": "agent", "scope": "write", "csrf": csrf}).text.split('<pre class="token">')[1].split("</pre>")[0]
    rd = client.post("/tokens", data={"name": "ro", "scope": "read", "csrf": csrf}).text.split('<pre class="token">')[1].split("</pre>")[0]
    client.cookies.clear()
    H = lambda t: {"Authorization": f"Bearer {t}"}
    assert client.get("/api/ideas").status_code == 401
    assert client.get("/api/ideas", headers=H("bad")).status_code == 401
    assert client.post("/api/ideas", json={"title": "t"}, headers=H(rd)).status_code == 403
    iid = client.post("/api/ideas", json={"title": "graph nets", "body_md": "retrieval"}, headers=H(wr)).json()["id"]
    src = {"url": "https://arxiv.org/abs/1", "title": "P", "kind": "paper", "year": 2024}
    assert client.post(f"/api/ideas/{iid}/sources", json=src, headers=H(wr)).status_code == 201
    assert client.post(f"/api/ideas/{iid}/sources", json=src, headers=H(wr)).json()["created"] is False
    assert client.post(f"/api/ideas/{iid}/sources", json={"url": "javascript:alert(1)"}, headers=H(wr)).status_code == 422
    assert client.post(f"/api/ideas/{iid}/notes", json={"body_md": "# r"}, headers=H(wr)).status_code == 201
    g = client.get(f"/api/ideas/{iid}", headers=H(rd)).json()
    assert len(g["sources"]) == 1 and g["sources"][0]["added_by"] == "agent" and len(g["notes"]) == 1
    assert len(client.get("/api/ideas?q=retrieval", headers=H(rd)).json()) == 1
    assert client.get('/api/ideas?q="NEAR(', headers=H(rd)).status_code == 200
    client.patch(f"/api/ideas/{iid}", json={"title": "renamed"}, headers=H(wr))
    assert client.get("/api/ideas?q=renamed", headers=H(rd)).json()[0]["id"] == iid


def test_setup_flow(tmp_path, monkeypatch):
    monkeypatch.delenv("ATHENA_ADMIN_PASSWORD")
    app.state.db_path = str(tmp_path / "s.db")
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/setup"
        assert c.get("/login", follow_redirects=False).headers["location"] == "/setup"
        assert c.post("/setup", data={"password": "short", "confirm": "short"}).status_code == 422
        assert c.post("/setup", data={"password": "a" * 12, "confirm": "b" * 12}).status_code == 422
        assert c.post("/setup", data={"password": "a" * 12, "confirm": "a" * 12}, follow_redirects=False).status_code == 303
        assert c.get("/setup").status_code == 404
        assert c.post("/setup", data={"password": "z" * 12, "confirm": "z" * 12}).status_code == 404
        assert c.post("/login", data={"password": "a" * 12}, follow_redirects=False).status_code == 303


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_export_import_roundtrip(client, tmp_path):
    csrf = login(client)
    client.post("/ideas", data={"title": "idea one", "summary": "s", "csrf": csrf})
    client.post("/ideas/1/sources", data={"url": "https://x.org/a", "title": "A", "year": "2023", "csrf": csrf})
    client.post("/ideas/1/notes", data={"body_md": "hello", "csrf": csrf})
    exp = client.get("/export.json")
    assert exp.status_code == 200
    data = exp.json()
    assert data["ideas"][0]["sources"][0]["url"] == "https://x.org/a"

    # import into a fresh instance
    app.state.db_path = str(tmp_path / "other.db")
    auth._attempts.clear()
    with TestClient(app) as c2:
        csrf2 = login(c2)
        up = lambda payload: c2.post("/import", data={"csrf": csrf2}, files={"file": ("e.json", payload, "application/json")}, follow_redirects=False)
        assert up(exp.content).status_code == 303
        assert up(exp.content).status_code == 303  # idempotent
        assert c2.get("/export.json").json()["ideas"] == data["ideas"]
        assert up(b'{"version":1,"ideas":[{"title":"x"}]}').status_code == 422
        evil = {"version": 1, "ideas": [{**data["ideas"][0], "sources": [{**data["ideas"][0]["sources"][0], "url": "javascript:alert(1)"}]}]}
        import json
        assert up(json.dumps(evil).encode()).status_code == 422


def test_bibtex_roundtrip(client):
    from app import bibtex
    csrf = login(client)
    client.post("/ideas", data={"title": "t", "csrf": csrf})
    bib = """@inproceedings{vaswani2017,
      title = {Attention {Is} All You Need},
      author = {Vaswani, Ashish and Shazeer, Noam},
      year = 2017, doi = {10.5555/3295222.3295349}
    }
    @misc{nourl, title={no link}}
    @article{x, title="Has url", url={https://arxiv.org/abs/1}, year={2020}}"""
    parsed = bibtex.parse(bib)
    assert [p["url"] for p in parsed] == ["https://doi.org/10.5555/3295222.3295349", "https://arxiv.org/abs/1"]
    assert parsed[0]["title"] == "Attention Is All You Need" and parsed[0]["year"] == 2017
    client.post("/ideas/1/bibtex", data={"bib": bib, "csrf": csrf})
    out = client.get("/ideas/1/export.bib")
    assert out.text.count("@") == 2 and "doi.org" in out.text


def test_migration_from_v1(tmp_path):
    path = str(tmp_path / "old.db")
    import sqlite3
    old = sqlite3.connect(path)
    old.executescript(db.MIGRATIONS[0])
    old.execute("PRAGMA user_version=1")
    old.execute("INSERT INTO ideas(title) VALUES('kept')")
    old.commit(); old.close()
    con = db.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert con.execute("SELECT title FROM ideas").fetchone()[0] == "kept"
    assert con.execute("SELECT 1 FROM sqlite_master WHERE name='notes_idea'").fetchone()


def test_security_headers_and_no_inline_code(client):
    csrf = login(client)
    client.post("/ideas", data={"title": "t", "csrf": csrf})
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers["content-security-policy"]
    import re
    for path in ("/", "/ideas/1", "/unsorted", "/settings"):
        html = client.get(path).text
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), path   # only external scripts
        assert " style=" not in html and "<style" not in html and " onclick=" not in html, path


def main_of(client, path):
    return client.get(path).text.split("<main>")[1]


def test_projects_ui(client):
    csrf = login(client)
    r = client.post("/projects", data={"name": "Thesis", "description": "d", "csrf": csrf}, follow_redirects=False)
    assert r.headers["location"] == "/p/1"
    assert client.post("/projects", data={"name": "Thesis", "csrf": csrf}).status_code == 422  # duplicate
    client.post("/ideas", data={"title": "in project", "project_id": "1", "csrf": csrf})
    client.post("/ideas", data={"title": "loose", "project_id": "", "csrf": csrf})
    assert client.post("/ideas", data={"title": "x", "project_id": "99", "csrf": csrf}).status_code == 422
    assert "in project" in main_of(client, "/p/1") and "loose" not in main_of(client, "/p/1")
    assert "loose" in main_of(client, "/unsorted")
    # move idea 2 into the project, then back out
    base = {"title": "loose", "status": "seed", "csrf": csrf}
    client.post("/ideas/2", data={**base, "project_id": "1"})
    assert "loose" in main_of(client, "/p/1")
    client.post("/ideas/2", data={**base, "project_id": ""})
    assert "loose" not in main_of(client, "/p/1")
    # source with empty year (browsers send "") must work
    assert client.post("/ideas/1/sources", data={"url": "https://a.org/x", "year": "", "csrf": csrf}, follow_redirects=False).status_code == 303
    # deleting the project keeps its ideas
    client.post("/projects/1/delete", data={"csrf": csrf})
    assert client.get("/p/1").status_code == 404 and "in project" in main_of(client, "/unsorted")


def test_projects_api_and_export(client, tmp_path):
    csrf = login(client)
    tok = client.post("/tokens", data={"name": "a", "scope": "write", "csrf": csrf}).text.split('<pre class="token">')[1].split("</pre>")[0]
    H = {"Authorization": f"Bearer {tok}"}
    pid = client.post("/api/projects", json={"name": "P"}, headers=H).json()["id"]
    assert client.post("/api/projects", json={"name": "P"}, headers=H).status_code == 409
    a = client.post("/api/ideas", json={"title": "a", "project_id": pid}, headers=H).json()["id"]
    b = client.post("/api/ideas", json={"title": "b"}, headers=H).json()["id"]
    assert client.post("/api/ideas", json={"title": "c", "project_id": 99}, headers=H).status_code == 422
    assert [i["id"] for i in client.get(f"/api/ideas?project_id={pid}", headers=H).json()] == [a]
    assert [i["id"] for i in client.get("/api/ideas?project_id=0", headers=H).json()] == [b]
    client.patch(f"/api/ideas/{b}", json={"project_id": pid}, headers=H)
    assert len(client.get(f"/api/ideas?project_id={pid}", headers=H).json()) == 2
    client.patch(f"/api/ideas/{b}", json={"project_id": 0}, headers=H)
    assert client.get(f"/api/ideas/{b}", headers=H).json()["project_id"] is None
    assert client.get("/api/projects", headers=H).json()[0]["n"] == 1

    exp = client.get("/api/export", headers=H).json()
    assert exp["projects"][0]["name"] == "P" and {i["title"]: i["project"] for i in exp["ideas"]} == {"a": "P", "b": None}
    import json
    app.state.db_path = str(tmp_path / "other.db")
    auth._attempts.clear()
    with TestClient(app) as c2:
        csrf2 = login(c2)
        up = lambda payload: c2.post("/import", data={"csrf": csrf2}, files={"file": ("e.json", payload, "application/json")}, follow_redirects=False)
        assert up(json.dumps(exp).encode()).status_code == 303
        assert "/ideas/1" in main_of(c2, "/p/1")
        # export from v0.1.x had no "projects" key and no "project" per idea
        old = {"version": 1, "ideas": [{k: v for k, v in i.items() if k not in ("project", "project_id")} for i in exp["ideas"]]}
        old["ideas"][0]["title"] = "old-style"
        assert up(json.dumps(old).encode()).status_code == 303
        assert "old-style" in main_of(c2, "/unsorted")


def test_migration_v2_to_v3_keeps_data(tmp_path):
    import sqlite3
    path = str(tmp_path / "v2.db")
    old = sqlite3.connect(path)
    for m in db.MIGRATIONS[:2]:
        old.executescript(m)
    old.execute("PRAGMA user_version=2")
    old.execute("INSERT INTO ideas(title) VALUES('survivor')")
    old.commit(); old.close()
    con = db.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS) >= 3
    row = con.execute("SELECT title, project_id FROM ideas").fetchone()
    assert row["title"] == "survivor" and row["project_id"] is None
