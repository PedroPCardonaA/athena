import os
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse

import nh3
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, field_validator

from . import auth, db

HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
_md = MarkdownIt("js-default")  # raw html disabled


def render_md(text: str) -> str:
    return nh3.clean(_md.render(text or ""))


templates.env.filters["md"] = render_md


@asynccontextmanager
async def lifespan(app):
    con = db.connect(app.state.db_path)
    auth.bootstrap(con)
    con.close()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.state.db_path = None  # None -> db.DB_PATH
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def get_con(request: Request):
    con = db.connect(request.app.state.db_path)
    try:
        yield con
    finally:
        con.close()


# ---------- UI session handling ----------

class NeedLogin(Exception):
    pass


@app.exception_handler(NeedLogin)
async def _need_login(request, exc):
    return RedirectResponse("/login", 303)


def session(request: Request, con=Depends(get_con)):
    s = auth.read_session(con, request.cookies.get(auth.COOKIE))
    if not s:
        raise NeedLogin()
    return s


async def csrf(request: Request, s=Depends(session)):
    form = await request.form()
    if not auth.csrf_ok(s, form.get("csrf", "")):
        raise HTTPException(403, "bad csrf token")


def page(request, name, s, **ctx):
    return templates.TemplateResponse(request, name, {"csrf": s["csrf"], "statuses": db.STATUSES, "kinds": db.KINDS, **ctx})


def safe_url(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("url must be http(s)")
    return url.strip()


@app.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
def login(request: Request, password: str = Form(...), con=Depends(get_con)):
    if auth.rate_limited() or not auth.check_password(con, password):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid or too many attempts"}, status_code=401)
    resp = RedirectResponse("/", 303)
    resp.set_cookie(auth.COOKIE, auth.new_session(con), max_age=auth.SESSION_MAX_AGE, httponly=True,
                    samesite="strict", secure=auth.COOKIE_SECURE)
    return resp


@app.post("/logout", dependencies=[Depends(csrf)])
def logout():
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- UI ----------

@app.get("/")
def index(request: Request, q: str = "", status: str = "", s=Depends(session), con=Depends(get_con)):
    return page(request, "index.html", s, ideas=db.list_ideas(con, q[:200], status), q=q, status=status)


@app.post("/ideas", dependencies=[Depends(csrf)])
def ui_create(title: str = Form(..., min_length=1, max_length=300), summary: str = Form("", max_length=2000),
              status: Literal[db.STATUSES] = Form("seed"), tags: str = Form("", max_length=300), con=Depends(get_con)):
    iid = db.create_idea(con, title.strip(), summary, "", status, tags)
    return RedirectResponse(f"/ideas/{iid}", 303)


def _idea_or_404(con, iid):
    idea = db.get_idea(con, iid)
    if not idea:
        raise HTTPException(404)
    return idea


@app.get("/ideas/{iid}")
def detail(request: Request, iid: int, s=Depends(session), con=Depends(get_con)):
    return page(request, "idea.html", s, idea=_idea_or_404(con, iid), sources=db.sources_of(con, iid), notes=db.notes_of(con, iid))


@app.post("/ideas/{iid}", dependencies=[Depends(csrf)])
def ui_update(iid: int, title: str = Form(..., min_length=1, max_length=300), summary: str = Form("", max_length=2000),
              body_md: str = Form("", max_length=100_000), status: Literal[db.STATUSES] = Form(...),
              tags: str = Form("", max_length=300), con=Depends(get_con)):
    _idea_or_404(con, iid)
    db.update_idea(con, iid, title=title.strip(), summary=summary, body_md=body_md, status=status, tags=tags)
    return RedirectResponse(f"/ideas/{iid}", 303)


@app.post("/ideas/{iid}/delete", dependencies=[Depends(csrf)])
def ui_delete(iid: int, con=Depends(get_con)):
    db.delete_idea(con, iid)
    return RedirectResponse("/", 303)


@app.post("/ideas/{iid}/sources", dependencies=[Depends(csrf)])
def ui_add_source(iid: int, url: str = Form(..., max_length=2000), title: str = Form("", max_length=500),
                  authors: str = Form("", max_length=500), year: int | None = Form(None, ge=1000, le=2100),
                  kind: Literal[db.KINDS] = Form("other"), note: str = Form("", max_length=5000), con=Depends(get_con)):
    _idea_or_404(con, iid)
    try:
        url = safe_url(url)
    except ValueError:
        raise HTTPException(422, "url must be http(s)")
    db.add_source(con, iid, url, title, authors, year, kind, note, "user")
    return RedirectResponse(f"/ideas/{iid}", 303)


@app.post("/sources/{sid}/delete", dependencies=[Depends(csrf)])
def ui_del_source(sid: int, con=Depends(get_con)):
    row = con.execute("SELECT idea_id FROM sources WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404)
    con.execute("DELETE FROM sources WHERE id=?", (sid,))
    con.commit()
    return RedirectResponse(f"/ideas/{row['idea_id']}", 303)


@app.post("/ideas/{iid}/notes", dependencies=[Depends(csrf)])
def ui_add_note(iid: int, body_md: str = Form(..., min_length=1, max_length=100_000), con=Depends(get_con)):
    _idea_or_404(con, iid)
    db.add_note(con, iid, body_md, "user")
    return RedirectResponse(f"/ideas/{iid}", 303)


@app.post("/notes/{nid}/delete", dependencies=[Depends(csrf)])
def ui_del_note(nid: int, con=Depends(get_con)):
    row = con.execute("SELECT idea_id FROM notes WHERE id=?", (nid,)).fetchone()
    if not row:
        raise HTTPException(404)
    con.execute("DELETE FROM notes WHERE id=?", (nid,))
    con.commit()
    return RedirectResponse(f"/ideas/{row['idea_id']}", 303)


@app.get("/tokens")
def tokens_page(request: Request, s=Depends(session), con=Depends(get_con)):
    rows = con.execute("SELECT id,name,scope,last_used FROM api_tokens ORDER BY id").fetchall()
    return page(request, "tokens.html", s, tokens=rows, new_token=None)


@app.post("/tokens", dependencies=[Depends(csrf)])
def tokens_create(request: Request, name: str = Form(..., min_length=1, max_length=80),
                  scope: Literal["read", "write"] = Form("write"), s=Depends(session), con=Depends(get_con)):
    tok = auth.create_token(con, name.strip(), scope)
    rows = con.execute("SELECT id,name,scope,last_used FROM api_tokens ORDER BY id").fetchall()
    return page(request, "tokens.html", s, tokens=rows, new_token=tok)


@app.post("/tokens/{tid}/delete", dependencies=[Depends(csrf)])
def tokens_delete(tid: int, con=Depends(get_con)):
    con.execute("DELETE FROM api_tokens WHERE id=?", (tid,))
    con.commit()
    return RedirectResponse("/tokens", 303)


# ---------- REST API (bearer token) ----------

def api_auth(request: Request, con=Depends(get_con)):
    h = request.headers.get("authorization", "")
    tok = auth.lookup_token(con, h[7:]) if h.lower().startswith("bearer ") else None
    if not tok:
        raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
    if request.method not in ("GET", "HEAD") and tok["scope"] != "write":
        raise HTTPException(403, "read-only token")
    return tok


class IdeaIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field("", max_length=2000)
    body_md: str = Field("", max_length=100_000)
    status: Literal[db.STATUSES] = "seed"
    tags: str = Field("", max_length=300)


class IdeaPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    summary: str | None = Field(None, max_length=2000)
    body_md: str | None = Field(None, max_length=100_000)
    status: Literal[db.STATUSES] | None = None
    tags: str | None = Field(None, max_length=300)


class SourceIn(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field("", max_length=500)
    authors: str = Field("", max_length=500)
    year: int | None = Field(None, ge=1000, le=2100)
    kind: Literal[db.KINDS] = "other"
    note: str = Field("", max_length=5000)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v):
        return safe_url(v)


class NoteIn(BaseModel):
    body_md: str = Field(min_length=1, max_length=100_000)
    kind: Literal[db.NOTE_KINDS] = "agent_report"


def _d(rows):
    return [dict(r) for r in rows]


@app.get("/api/ideas", dependencies=[Depends(api_auth)])
def api_list(q: str = "", status: str = "", con=Depends(get_con)):
    return _d(db.list_ideas(con, q[:200], status))


@app.post("/api/ideas", status_code=201, dependencies=[Depends(api_auth)])
def api_create(body: IdeaIn, con=Depends(get_con)):
    return {"id": db.create_idea(con, **body.model_dump())}


@app.get("/api/ideas/{iid}", dependencies=[Depends(api_auth)])
def api_get(iid: int, con=Depends(get_con)):
    idea = _idea_or_404(con, iid)
    return {**dict(idea), "sources": _d(db.sources_of(con, iid)), "notes": _d(db.notes_of(con, iid))}


@app.patch("/api/ideas/{iid}", dependencies=[Depends(api_auth)])
def api_patch(iid: int, body: IdeaPatch, con=Depends(get_con)):
    _idea_or_404(con, iid)
    db.update_idea(con, iid, **body.model_dump())
    return {"ok": True}


@app.post("/api/ideas/{iid}/sources", status_code=201, dependencies=[Depends(api_auth)])
def api_add_source(iid: int, body: SourceIn, con=Depends(get_con)):
    _idea_or_404(con, iid)
    sid, created = db.add_source(con, iid, **body.model_dump(), added_by="agent")
    return JSONResponse({"id": sid, "created": created}, status_code=201 if created else 200)


@app.post("/api/ideas/{iid}/notes", status_code=201, dependencies=[Depends(api_auth)])
def api_add_note(iid: int, body: NoteIn, con=Depends(get_con)):
    _idea_or_404(con, iid)
    return {"id": db.add_note(con, iid, body.body_md, body.kind)}
