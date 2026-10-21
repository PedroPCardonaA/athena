"""Minimal BibTeX reader/writer for source lists (no external deps)."""
import re

_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]*)\s*,", re.S)
_FIELD = re.compile(r"(\w+)\s*=\s*", re.S)
PAPER_TYPES = {"article", "inproceedings", "conference", "incollection", "phdthesis", "mastersthesis", "techreport", "book", "inbook", "proceedings"}


def _value(text, i):
    """Read a field value starting at text[i]; returns (value, next_index)."""
    n = len(text)
    if i < n and text[i] == "{":
        depth, j = 1, i + 1
        while j < n and depth:
            depth += (text[j] == "{") - (text[j] == "}")
            j += 1
        return text[i + 1 : j - 1], j
    if i < n and text[i] == '"':
        j = text.find('"', i + 1)
        j = n if j < 0 else j
        return text[i + 1 : j], j + 1
    m = re.match(r"[^,}\s]+", text[i:])
    return (m.group(0), i + m.end()) if m else ("", i)


def _clean(v):
    return re.sub(r"\s+", " ", v.replace("{", "").replace("}", "")).strip()


def parse(text: str):
    """Return source dicts (url,title,authors,year,kind,note) for entries with a url or doi."""
    out = []
    for m in _ENTRY.finditer(text):
        etype, i, fields = m.group(1).lower(), m.end(), {}
        while True:
            f = _FIELD.search(text, i)
            nxt = _ENTRY.search(text, i)
            if not f or (nxt and nxt.start() < f.start()):
                break
            val, i = _value(text, f.end())
            fields[f.group(1).lower()] = _clean(val)
        url = fields.get("url", "")
        doi = fields.get("doi", "")
        if not url and doi:
            url = "https://doi.org/" + doi.removeprefix("https://doi.org/")
        if not re.match(r"https?://\S+$", url):
            continue
        year = fields.get("year", "")
        out.append({
            "url": url,
            "title": fields.get("title", "")[:500],
            "authors": fields.get("author", "").replace(" and ", ", ")[:500],
            "year": int(year) if year.isdigit() and 1000 <= int(year) <= 2100 else None,
            "kind": "paper" if etype in PAPER_TYPES else "other",
            "note": fields.get("abstract", "")[:5000],
        })
    return out


def dump(sources) -> str:
    entries = []
    for s in sources:
        first = (s["authors"].split(",")[0].split()[-1:] or ["anon"])[0]
        key = re.sub(r"\W", "", f"{first}{s['year'] or ''}{s['id']}") or f"src{s['id']}"
        etype = "article" if s["kind"] == "paper" else "misc"
        f = [("title", s["title"] or s["url"]), ("author", s["authors"].replace(", ", " and ")),
             ("year", s["year"] or ""), ("url", s["url"])]
        body = ",\n".join(f"  {k} = {{{str(v).replace('{', '').replace('}', '')}}}" for k, v in f if v != "")
        entries.append(f"@{etype}{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"
