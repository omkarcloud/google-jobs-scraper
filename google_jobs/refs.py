"""Reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrLinkField convention — never a sibling `url` / `id`
pair). Resolvers return plain JSON values so the validated params stay
usable as a response-cache key.

  query    "data analyst jobs chicago" | any google.<tld>/search link
           (its q, and gl / hl through the schema) — shared with
           google_search.refs
  job      a job id ("rE71TFwWpTWbd28uAAAAAA==", as returned by search) |
           a Google Jobs link: the `link` of a search result
           (/search?q=…&udm=8&htidocid=…), a Google share link
           (…ibp=htl;jobs&q=…&htidocid=…#fpstate=…), a link with
           #vhid=vt%3D20/docid%3D<id> | "vt=20/docid=<id>"
           -> {"id": …, "query": … or None}
  company  "Capital One" | a google.<tld>/search link whose q names the
           company ("Jobs at Capital One", "Capital One jobs")
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

from google_search.refs import is_google_link, params_of, resolve_query  # noqa: F401 (re-exported)

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{16,40}={0,2}$")
_DOCID_RE = re.compile(r"(?:htidocid=|docid(?:=|%3D))([A-Za-z0-9_\-]{16,40}(?:=|%3D){0,2})", re.I)


def is_job_id(value):
    return bool(_ID_RE.match(unquote(value or "").strip()))


def resolve_job(value):
    """A job id or Google Jobs link -> {"id", "query"}."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("job must not be empty")
    if is_google_link(raw):
        m = _DOCID_RE.search(raw)
        if not m:
            raise ValueError("a Google Jobs link must carry the job id (htidocid= or #vhid=…docid=)")
        parts = urlparse(raw if "://" in raw else "https://" + raw.lstrip("/"))
        params = {k: v[0] for k, v in parse_qs(parts.query).items() if v}
        fragment = {k: v[0] for k, v in parse_qs(parts.fragment).items() if v}
        query = (params.get("q") or fragment.get("htiq") or params.get("htiq") or "").strip() or None
        return {"id": unquote(m.group(1)), "query": query}
    m = re.fullmatch(r"vt=\d+/docid=(.+)", unquote(raw))
    candidate = m.group(1) if m else unquote(raw)
    if not _ID_RE.match(candidate):
        raise ValueError("job must be a job id (like rE71TFwWpTWbd28uAAAAAA==) or a Google Jobs link")
    return {"id": candidate, "query": None}


def split_jobs(value):
    """'id1, id2, https://www.google.com/search?…shem=a,b…' -> items.
    Google share links carry commas themselves, so a fragment that is
    neither a link nor an id is glued back onto the link before it."""
    items = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if items and is_google_link(items[-1]) and not is_google_link(part) and not is_job_id(part):
            items[-1] += "," + part
        else:
            items.append(part)
    return items


def resolve_company(value):
    """A company name or a Google search link naming it -> the name."""
    raw = (value or "").strip()
    if is_google_link(raw):
        q = params_of(raw).get("q")
        if not q:
            raise ValueError("a Google link must carry a q= naming the company")
        raw = q
    elif raw.lower().startswith(("http://", "https://", "//")):
        raise ValueError("company must be a company name or a google.com/search link")
    name = re.sub(r"^\s*jobs?\s+(?:at|@)\s+", "", raw, flags=re.I)
    name = re.sub(r"\s+jobs?\s*$", "", name, flags=re.I).strip()
    if not name:
        raise ValueError("company must not be empty")
    return name
