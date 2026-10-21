import json
import subprocess
import sys

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app import db
from app.athena_mcp import build

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dbfile(tmp_path):
    return str(tmp_path / "m.db")


async def call(client, tool, /, **args):
    res = await client.call_tool(tool, args)
    if res.isError:
        return {"error": res.content[0].text}
    return res.structuredContent


async def test_lists_everything(dbfile):
    async with create_connected_server_and_client_session(build(db_path=dbfile)._mcp_server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert {"list_projects", "get_project", "list_ideas", "get_idea", "search", "get_project_digest", "create_project",
                "update_project", "set_project_summary", "create_idea", "update_idea", "add_source", "add_sources",
                "add_note"} <= set(tools)
        assert not any(n.startswith("delete") for n in tools)           # destructive ops stay in the UI
        assert tools["list_projects"].annotations.readOnlyHint is True
        assert tools["update_idea"].annotations.destructiveHint is True
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert {"summarize_project", "improve_idea", "research_idea", "find_related_work", "weekly_review"} <= prompts
        res = {str(r.uri) for r in (await c.list_resources()).resources}
        assert "athena://projects" in res
        tpl = {t.uriTemplate for t in (await c.list_resource_templates()).resourceTemplates}
        assert {"athena://project/{project_id}", "athena://idea/{idea_id}"} <= tpl
        init = c.get_server_capabilities()
        assert init.tools and init.prompts and init.resources


async def test_read_only_hides_write_tools(dbfile):
    async with create_connected_server_and_client_session(build(read_only=True, db_path=dbfile)._mcp_server) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "get_project" in names and not names & {"create_idea", "add_source", "update_idea", "set_project_summary", "add_note"}
        p = (await c.get_prompt("summarize_project", {"project_id": "1"})).messages[0].content.text
        assert "set_project_summary" not in p


async def test_full_workflow(dbfile):
    async with create_connected_server_and_client_session(build(db_path=dbfile)._mcp_server) as c:
        pid = (await call(c, "create_project", name="Thesis", description="main"))["id"]
        assert "error" in await call(c, "create_project", name="Thesis")                 # duplicate
        a = (await call(c, "create_idea", title="Graph RAG", summary="s", tags="a,b", project_id=pid, status="exploring"))["id"]
        b = (await call(c, "create_idea", title="Loose"))["id"]
        assert "error" in await call(c, "create_idea", title="x", project_id=99)
        assert "error" in await call(c, "create_idea", title="x", status="bogus")

        src = await call(c, "add_source", idea_id=a, url="https://arxiv.org/abs/1", title="P", kind="paper", year=2020, note="why")
        assert src["created"] is True
        assert (await call(c, "add_source", idea_id=a, url="https://arxiv.org/abs/1"))["created"] is False
        assert "error" in await call(c, "add_source", idea_id=a, url="javascript:alert(1)")
        assert "error" in await call(c, "add_source", url="https://x.org")                      # no target
        assert "error" in await call(c, "add_source", url="https://x.org", idea_id=a, project_id=pid)  # two targets
        batch = await call(c, "add_sources", project_id=pid, sources=[
            {"url": "https://arxiv.org/abs/1", "title": "P again"}, {"url": "https://doi.org/10.1/z", "title": "Z"}])
        assert batch["added"] == 2 and batch["skipped"] == 0       # unique per project; project-level copy is separate
        assert "error" in await call(c, "add_sources", project_id=pid, sources=[{"url": "ftp://bad"}])
        assert "error" in await call(c, "add_sources", project_id=pid, sources=[{"url": f"https://a.org/{i}"} for i in range(51)])

        assert "id" in await call(c, "add_note", idea_id=a, body_md="# report")
        assert "error" in await call(c, "add_note", idea_id=999, body_md="x")

        proj = await call(c, "get_project", project_id=pid)
        assert [i["id"] for i in proj["ideas"]] == [a]
        urls = {s["url"]: s for s in proj["all_sources"]}
        assert set(urls) == {"https://arxiv.org/abs/1", "https://doi.org/10.1/z"}
        assert urls["https://arxiv.org/abs/1"]["direct"] and urls["https://arxiv.org/abs/1"]["cited_by"][0]["id"] == a
        assert urls["https://arxiv.org/abs/1"]["agent"] is True

        await call(c, "update_idea", idea_id=b, project_id=pid, status="active")
        assert {i["id"] for i in (await call(c, "list_ideas", project_id=pid))["ideas"]} == {a, b}
        await call(c, "update_idea", idea_id=b, project_id=0)
        assert [i["id"] for i in (await call(c, "list_ideas", project_id=0))["ideas"]] == [b]
        assert (await call(c, "list_ideas", status="active"))["ideas"][0]["id"] == b
        assert "error" in await call(c, "update_idea", idea_id=b, project_id=77)
        await call(c, "update_idea", idea_id=a, title="Graph RAG v2")
        full = await call(c, "get_idea", idea_id=a)
        assert full["idea"]["title"] == "Graph RAG v2" and full["idea"]["summary"] == "s"       # untouched field kept
        assert len(full["sources"]) == 1 and full["notes_total"] == 1

        await call(c, "set_project_summary", project_id=pid, summary_md="## Goal\nx")
        await call(c, "update_project", project_id=pid, description="new")
        assert (await call(c, "get_project", project_id=pid))["project"]["summary_md"].startswith("## Goal")
        assert (await call(c, "list_projects"))["projects"][0]["has_summary"] is True

        s = await call(c, "search", query="arxiv")
        assert s["sources"] and (await call(c, "search", query="report"))["notes"]
        assert (await call(c, "search", query="graph"))["ideas"][0]["id"] == a
        d = (await call(c, "get_project_digest", project_id=pid, max_chars=1000))["markdown"]
        assert "Graph RAG v2" in d and len(d) <= 1100
        assert "error" in await call(c, "get_project_digest", project_id=404)

        # resources + prompts
        r = await c.read_resource("athena://project/%d" % pid)
        assert "Graph RAG v2" in r.contents[0].text
        r = await c.read_resource("athena://idea/%d" % a)
        assert "arxiv.org" in r.contents[0].text
        p = await c.get_prompt("research_idea", {"idea_id": str(a)})
        assert "add_sources" in p.messages[0].content.text and "untrusted" in p.messages[0].content.text


async def test_agent_writes_are_labelled(dbfile):
    async with create_connected_server_and_client_session(build(db_path=dbfile)._mcp_server) as c:
        i = (await call(c, "create_idea", title="t"))["id"]
        await call(c, "add_source", idea_id=i, url="https://a.org")
    con = db.connect(dbfile)
    assert con.execute("SELECT added_by FROM sources").fetchone()[0] == "agent"


def test_stdio_subprocess_handshake_is_clean(dbfile):
    """The real entrypoint: only JSON-RPC on stdout, works with ATHENA_DB, honours --read-only."""
    import os
    env = {**os.environ, "ATHENA_DB": dbfile}
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    for flags, expect_write in (([], True), (["--read-only"], False)):
        proc = subprocess.Popen([sys.executable, "-m", "app.athena_mcp", *flags], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            for m in msgs:
                proc.stdin.write(json.dumps(m) + "\n")
                proc.stdin.flush()
            seen = []
            while True:
                line = proc.stdout.readline()
                assert line, "server exited before answering"
                msg = json.loads(line)                       # every stdout line must be JSON-RPC
                assert msg.get("jsonrpc") == "2.0"
                seen.append(msg)
                if msg.get("id") == 2:
                    break
            tools = {t["name"] for t in msg["result"]["tools"]}
            assert ("create_idea" in tools) is expect_write
        finally:
            proc.kill()
            proc.wait()
