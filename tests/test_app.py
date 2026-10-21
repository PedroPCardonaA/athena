import os
import pytest
from fastapi.testclient import TestClient

os.environ["IDEAS_ADMIN_PASSWORD"] = "correct horse battery staple"
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
    assert "<img" not in t and 'href="javascript' not in t


def test_api_flow(client):
    csrf = login(client)
    wr = client.post("/tokens", data={"name": "agent", "scope": "write", "csrf": csrf}).text.split("<pre>")[1].split("</pre>")[0]
    rd = client.post("/tokens", data={"name": "ro", "scope": "read", "csrf": csrf}).text.split("<pre>")[1].split("</pre>")[0]
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
