#!/usr/bin/env python3
"""Tiny stdlib client for Athena. Config: ~/.config/athena/config (JSON: url, token)."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CFG = os.path.expanduser("~/.config/athena/config")
if not os.path.exists(CFG):  # v0.1.x location
    CFG = os.path.expanduser("~/.config/ideas-saver/config")


def call(method, path, body=None):
    cfg = json.load(open(CFG))
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:500]}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--q", default=""); s.add_argument("--status", default="")
    s.add_argument("--project", type=int, help="project id (0 = unsorted)")
    sub.add_parser("projects")
    s = sub.add_parser("get"); s.add_argument("id", type=int)
    s = sub.add_parser("add-source"); s.add_argument("id", type=int); s.add_argument("--url", required=True)
    s.add_argument("--title", default=""); s.add_argument("--authors", default="")
    s.add_argument("--year", type=int); s.add_argument("--kind", default="other"); s.add_argument("--note", default="")
    s = sub.add_parser("add-note"); s.add_argument("id", type=int); s.add_argument("--kind", default="agent_report")
    s.add_argument("--file", help="markdown file; default stdin")
    a = p.parse_args()

    if a.cmd == "list":
        from urllib.parse import urlencode
        qs = {"q": a.q, "status": a.status}
        if a.project is not None:
            qs["project_id"] = a.project
        out = call("GET", "/api/ideas?" + urlencode(qs))
    elif a.cmd == "projects":
        out = call("GET", "/api/projects")
    elif a.cmd == "get":
        out = call("GET", f"/api/ideas/{a.id}")
    elif a.cmd == "add-source":
        out = call("POST", f"/api/ideas/{a.id}/sources", {k: v for k, v in dict(
            url=a.url, title=a.title, authors=a.authors, year=a.year, kind=a.kind, note=a.note).items() if v is not None})
    else:
        body = open(a.file).read() if a.file else sys.stdin.read()
        out = call("POST", f"/api/ideas/{a.id}/notes", {"body_md": body, "kind": a.kind})
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
