import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal

import nh3
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, field_validator

from . import auth, bibtex, db, service

HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
_md = MarkdownIt("js-default")  # raw html disabled


def render_md(text: str) -> str:
    return nh3.clean(_md.render(text or ""))


templates.env.filters["md"] = render_md
templates.env.filters["domain"] = service.domain


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
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; "
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
    con = db.connect(request.app.state.db_path)
    try:
        return RedirectResponse("/login" if auth.is_configured(con) else "/setup", 303)
    finally:
        con.close()


def session(request: Request, con=Depends(get_con)):
    s = auth.read_session(con, request.cookies.get(auth.COOKIE))
    if not s:
        raise NeedLogin()
    return s


async def csrf(request: Request, s=Depends(session)):
    form = await request.form()
    if not auth.csrf_ok(s, form.get("csrf", "")):
        raise HTTPException(403, "bad csrf token")


def page(request, name, s, con, **ctx):
    projects = db.list_projects(con)
    return templates.TemplateResponse(request, name, {
        "csrf": s["csrf"], "statuses": db.STATUSES, "kinds": db.KINDS, "projects": projects,
        "pnames": {p["id"]: p["name"] for p in projects}, "nav_ideas": db.nav_ideas(con), **ctx})


def opt_int(raw: str, lo=0, hi=10**9, what="value") -> int | None:
    """Parse an optional integer from a form field ('' -> None)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        raise HTTPException(422, f"{what} must be a number")
    if not lo <= v <= hi:
        raise HTTPException(422, f"{what} out of range")
    return v


def project_id_or_422(con, raw) -> int | None:
    pid = opt_int(raw, what="project") if isinstance(raw, str) else raw
    if pid and not db.get_project(con, pid):
        raise HTTPException(422, "unknown project")
    return pid or None


@app.get("/healthz")
def healthz(con=Depends(get_con)):
    con.execute("SELECT 1")
    return {"ok": True}


@app.get("/setup")
def setup_form(request: Request, con=Depends(get_con)):
    if auth.is_configured(con):
        raise HTTPException(404)
    return templates.TemplateResponse(request, "setup.html", {"error": "", "min": auth.MIN_PASSWORD})


@app.post("/setup")
def setup(request: Request, password: str = Form(..., max_length=256), confirm: str = Form(..., max_length=256),
          con=Depends(get_con)):
    if auth.is_configured(con):
        raise HTTPException(404)
    err = ""
    if len(password) < auth.MIN_PASSWORD:
        err = f"Use at least {auth.MIN_PASSWORD} characters"
    elif password != confirm:
        err = "Passwords do not match"
    elif not auth.set_password(con, password):
        raise HTTPException(404)
    if err:
        return templates.TemplateResponse(request, "setup.html", {"error": err, "min": auth.MIN_PASSWORD}, status_code=422)
    return RedirectResponse("/login", 303)


@app.get("/login")
def login_form(request: Request, con=Depends(get_con)):
    if not auth.is_configured(con):
        return RedirectResponse("/setup", 303)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
def login(request: Request, password: str = Form(..., max_length=256), con=Depends(get_con)):
    if not auth.is_configured(con):
        return RedirectResponse("/setup", 303)
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


# ---------- UI: ideas ----------

@app.get("/")
def index(request: Request, q: str = "", status: str = "", s=Depends(session), con=Depends(get_con)):
    ideas = db.list_ideas(con, q[:200], status)
    return page(request, "index.html", s, con, ideas=ideas, q=q, status=status, current_project=None)


@app.post("/ideas", dependencies=[Depends(csrf)])
def ui_create(title: str = Form(..., min_length=1, max_length=300), summary: str = Form("", max_length=2000),
              status: Literal[db.STATUSES] = Form("seed"), tags: str = Form("", max_length=300),
              project_id: str = Form(""), con=Depends(get_con)):
    iid = db.create_idea(con, title.strip(), summary, "", status, tags, project_id_or_422(con, project_id))
    return RedirectResponse(f"/ideas/{iid}", 303)


def _idea_or_404(con, iid):
    idea = db.get_idea(con, iid)
    if not idea:
        raise HTTPException(404)
    return idea


@app.get("/ideas/{iid}")
def detail(request: Request, iid: int, s=Depends(session), con=Depends(get_con)):
    idea = _idea_or_404(con, iid)
    return page(request, "idea.html", s, con, idea=idea, sources=db.sources_of(con, iid), liked=db.liked_urls(con),
                notes=db.notes_of(con, iid), current_project=idea["project_id"])


@app.post("/ideas/{iid}", dependencies=[Depends(csrf)])
def ui_update(iid: int, title: str = Form(..., min_length=1, max_length=300), summary: str = Form("", max_length=2000),
              body_md: str = Form("", max_length=100_000), status: Literal[db.STATUSES] = Form(...),
              tags: str = Form("", max_length=300), project_id: str = Form(""), con=Depends(get_con)):
    _idea_or_404(con, iid)
    db.update_idea(con, iid, title=title.strip(), summary=summary, body_md=body_md, status=status, tags=tags,
                   project_id=project_id_or_422(con, project_id) or 0)
    return RedirectResponse(f"/ideas/{iid}", 303)


@app.post("/ideas/{iid}/delete", dependencies=[Depends(csrf)])
def ui_delete(iid: int, con=Depends(get_con)):
    db.delete_idea(con, iid)
    return RedirectResponse("/", 303)


@app.post("/ideas/{iid}/sources", dependencies=[Depends(csrf)])
def ui_add_source(iid: int, url: str = Form(..., max_length=2000), title: str = Form("", max_length=500),
                  authors: str = Form("", max_length=500), year: str = Form(""),
                  kind: Literal[db.KINDS] = Form("other"), note: str = Form("", max_length=5000), con=Depends(get_con)):
    _idea_or_404(con, iid)
    try:
        url = service.safe_url(url)
    except ValueError:
        raise HTTPException(422, "url must be http(s)")
    db.add_source(con, iid, url, title, authors, opt_int(year, 1000, 2100, "year"), kind, note, "user")
    return RedirectResponse(f"/ideas/{iid}", 303)


@app.post("/sources/like", dependencies=[Depends(csrf)])
def ui_like_source(url: str = Form(..., max_length=2000), next: str = Form("/", max_length=500), con=Depends(get_con)):
    try:
        url = service.safe_url(url)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.toggle_like(con, url)
    # only bounce back to our own project/idea pages, never an arbitrary location
    if not (next.startswith(("/p/", "/ideas/")) and "//" not in next and "\\" not in next):
        next = "/"
    return RedirectResponse(next, 303)


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


@app.get("/ideas/{iid}/export.bib")
def ui_bib(iid: int, s=Depends(session), con=Depends(get_con)):
    _idea_or_404(con, iid)
    return PlainTextResponse(bibtex.dump(db.sources_of(con, iid)), headers={
        "Content-Disposition": f'attachment; filename="idea-{iid}.bib"'})


@app.post("/ideas/{iid}/bibtex", dependencies=[Depends(csrf)])
def ui_import_bib(iid: int, bib: str = Form(..., max_length=500_000), con=Depends(get_con)):
    _idea_or_404(con, iid)
    for src in bibtex.parse(bib):
        db.add_source(con, iid, **src, added_by="user")
    return RedirectResponse(f"/ideas/{iid}", 303)


# ---------- UI: projects ----------

def _project_or_404(con, pid):
    p = db.get_project(con, pid)
    if not p:
        raise HTTPException(404)
    return p


@app.get("/p/{pid}")
def project_view(request: Request, pid: int, s=Depends(session), con=Depends(get_con)):
    proj = _project_or_404(con, pid)
    allsrc = service.rollup(con, pid)
    qp = request.query_params
    sf = {"sort": qp.get("sort", ""), "kind": qp.get("kind", ""), "origin": qp.get("origin", ""),
          "q": qp.get("q", "")[:200], "liked": qp.get("liked", "") == "1"}
    shown = service.sort_sources(allsrc, sf["sort"], sf["kind"], sf["liked"], sf["q"], sf["origin"])
    return page(request, "project.html", s, con, project=proj, ideas=db.list_ideas(con, project_id=pid),
                sources=shown, sources_total=len(allsrc), sf=sf, sort_options=service.SORTS,
                current_project=pid, error=qp.get("error", ""))


@app.get("/unsorted")
def unsorted_view(request: Request, s=Depends(session), con=Depends(get_con)):
    return page(request, "project.html", s, con, project=None, ideas=db.list_ideas(con, project_id=0),
                sources=[], sources_total=0, sf={}, sort_options=service.SORTS, current_project=0, error="")


@app.post("/projects", dependencies=[Depends(csrf)])
def ui_project_create(name: str = Form(..., min_length=1, max_length=80), description: str = Form("", max_length=1000),
                      con=Depends(get_con)):
    try:
        pid = db.create_project(con, name.strip(), description)
    except sqlite3.IntegrityError:
        raise HTTPException(422, "a project with that name already exists")
    return RedirectResponse(f"/p/{pid}", 303)


@app.post("/projects/{pid}", dependencies=[Depends(csrf)])
def ui_project_update(pid: int, name: str = Form(..., min_length=1, max_length=80),
                      description: str = Form("", max_length=1000), con=Depends(get_con)):
    _project_or_404(con, pid)
    try:
        db.update_project(con, pid, name.strip(), description)
    except sqlite3.IntegrityError:
        return RedirectResponse(f"/p/{pid}?error=name+already+exists", 303)
    return RedirectResponse(f"/p/{pid}", 303)


@app.post("/projects/{pid}/summary", dependencies=[Depends(csrf)])
def ui_project_summary(pid: int, summary_md: str = Form("", max_length=20_000), con=Depends(get_con)):
    _project_or_404(con, pid)
    db.set_project_summary(con, pid, summary_md)
    return RedirectResponse(f"/p/{pid}", 303)


@app.post("/projects/{pid}/sources", dependencies=[Depends(csrf)])
def ui_project_add_source(pid: int, url: str = Form(..., max_length=2000), title: str = Form("", max_length=500),
                          authors: str = Form("", max_length=500), year: str = Form(""),
                          kind: Literal[db.KINDS] = Form("other"), note: str = Form("", max_length=5000),
                          con=Depends(get_con)):
    _project_or_404(con, pid)
    try:
        service.add_source(con, project_id=pid, url=url, title=title, authors=authors,
                           year=opt_int(year, 1000, 2100, "year"), kind=kind, note=note)
    except ValueError:
        raise HTTPException(422, "url must be http(s)")
    return RedirectResponse(f"/p/{pid}#sources", 303)


@app.post("/project-sources/{sid}/delete", dependencies=[Depends(csrf)])
def ui_project_del_source(sid: int, con=Depends(get_con)):
    row = con.execute("SELECT project_id FROM project_sources WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404)
    con.execute("DELETE FROM project_sources WHERE id=?", (sid,))
    con.commit()
    return RedirectResponse(f"/p/{row['project_id']}#sources", 303)


@app.get("/p/{pid}/export.bib")
def ui_project_bib(pid: int, s=Depends(session), con=Depends(get_con)):
    _project_or_404(con, pid)
    rows = [{"id": n, **e} for n, e in enumerate(service.rollup(con, pid), 1)]
    return PlainTextResponse(bibtex.dump([{**r, "kind": r["kind"]} for r in rows]), headers={
        "Content-Disposition": f'attachment; filename="project-{pid}.bib"'})


@app.post("/p/{pid}/bibtex", dependencies=[Depends(csrf)])
def ui_project_import_bib(pid: int, bib: str = Form(..., max_length=500_000), con=Depends(get_con)):
    _project_or_404(con, pid)
    for src in bibtex.parse(bib):
        db.add_project_source(con, pid, **src, added_by="user")
    return RedirectResponse(f"/p/{pid}#sources", 303)


@app.post("/projects/{pid}/delete", dependencies=[Depends(csrf)])
def ui_project_delete(pid: int, con=Depends(get_con)):
    db.delete_project(con, pid)
    return RedirectResponse("/", 303)


# ---------- UI: backup + tokens ----------

@app.get("/export.json")
def ui_export(s=Depends(session), con=Depends(get_con)):
    return JSONResponse(db.export_all(con), headers={"Content-Disposition": 'attachment; filename="athena-export.json"'})


MAX_IMPORT = 20 * 1024 * 1024


@app.post("/import", dependencies=[Depends(csrf)])
async def ui_import(file: UploadFile = File(...), con=Depends(get_con)):
    raw = await file.read(MAX_IMPORT + 1)
    if len(raw) > MAX_IMPORT:
        raise HTTPException(413, "file too large")
    try:
        data = ExportIn.model_validate_json(raw).model_dump()
    except ValueError as e:
        raise HTTPException(422, f"invalid export file: {str(e)[:300]}")
    db.import_all(con, data)
    return RedirectResponse("/", 303)


@app.get("/settings")
def settings_page(request: Request, s=Depends(session), con=Depends(get_con)):
    return page(request, "settings.html", s, con, current_project=None)


# ---------- import/export models ----------

class IdeaIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field("", max_length=2000)
    body_md: str = Field("", max_length=100_000)
    status: Literal[db.STATUSES] = "seed"
    tags: str = Field("", max_length=300)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=1000)


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
        return service.safe_url(v)


class NoteIn(BaseModel):
    body_md: str = Field(min_length=1, max_length=100_000)
    kind: Literal[db.NOTE_KINDS] = "agent_report"


class ExportSource(SourceIn):
    added_by: Literal["user", "agent"] = "user"
    created_at: str = Field(max_length=40)
    liked: bool = False


class ExportNote(NoteIn):
    created_at: str = Field(max_length=40)


class ExportProject(ProjectIn):
    created_at: str = Field(max_length=40)
    summary_md: str = Field("", max_length=20_000)
    sources: list[ExportSource] = []


class ExportIdea(IdeaIn):
    created_at: str = Field(max_length=40)
    updated_at: str = Field(max_length=40)
    project: str | None = Field(None, max_length=80)
    sources: list[ExportSource] = []
    notes: list[ExportNote] = []


class ExportIn(BaseModel):
    version: Literal[1]
    projects: list[ExportProject] = []  # absent in v0.1.x exports
    ideas: list[ExportIdea]
