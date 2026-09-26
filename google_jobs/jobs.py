"""/google-jobs/* endpoints: job search (Google's own ranking, filters,
up to GOOGLE_JOBS_MAX_PAGES x 10 jobs), job details (single + batch),
a company's open jobs and job-search suggestions.

Cost model (each is one identity use, see google_jobs/fetch.py):
  search page 1      1 results page (+1 once per language for non-English
                     filter wording, memoised for 30 days)
  search page N      1 next-page callback when page N-1's token is
                     memoised, otherwise the chain is walked from the
                     nearest memoised page
  details            1 viewer callback for a job seen in a search within
                     GOOGLE_JOBS_JOB_MEMO_DAYS; else 1 results page (the
                     job pinned first via htidocid, needs the job's search
                     query — every `link` we return carries it) + 1 viewer
"""
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import quote_plus, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from google_jobs import fetch, parsers as P  # noqa: E402
from google_search import autocomplete as gs_autocomplete  # noqa: E402
from google_search.serp import resolve_goto  # noqa: E402
from google_search.shared import paged_result  # noqa: E402

PAGE_SIZE = 10
MAX_NUM_PAGES = 5
DATE_POSTED = ["any", "today", "3days", "week", "month"]
JOB_TYPES = ["full_time", "part_time", "contractor", "internship"]
# Google's own filter wording (hl=en): the date group is Yesterday / Last 3
# days / Last week / Last month, the job-type group Full time / Part time /
# Contract / Internship, the chip bar Remote / No degree.
EN_WORDS = {
    "date_posted": ["since yesterday", "in the last 3 days", "in the last week", "in the last month"],
    "job_type": ["full time", "part time", "contract", "internship"],
    "remote": "remote",
    "no_degree": "no degree",
}
NS_JOB = "google-jobs.memo.job"
NS_PAGE = "google-jobs.memo.page"
NS_WORDS = "google-jobs.memo.filter-words"
_memo_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="google-jobs-memo")
_words_lock = threading.Lock()


# ---- query assembly -------------------------------------------------------------------------------------

def _filter_words(query, country, language, radius):
    """The filter wording for `language`: built in for English, read once
    from a results page's filter links for other languages (the words are
    query-independent) and memoised."""
    if (language or "en").split("-")[0].lower() == "en":
        return EN_WORDS
    key = {"language": language}
    hit = fetch.memo.get(NS_WORDS, key)
    if hit:
        return hit
    with _words_lock:
        hit = fetch.memo.get(NS_WORDS, key)
        if hit:
            return hit
        html = fetch.results_page(query, country=country, language=language, radius=radius, label="filter-words")
        found = P.filter_suffixes(html, query)
        words = {k: found.get(k) or EN_WORDS[k] for k in EN_WORDS}
        if found.get("date_posted") and found.get("job_type"):
            fetch.memo.put(NS_WORDS, key, words, timedelta(days=30))
        return words


def build_query(query, location=None, country="US", language="en", date_posted=None, job_type=None, remote_only=None,
                no_degree=None, radius=None):
    """The query Google is sent: the search, the location, then Google's own
    filter wording (a filter IS its words — see fetch.py)."""
    parts = [query]
    if location:
        parts.append(location)
    base = " ".join(parts)
    if not ((date_posted and date_posted != "any") or job_type or remote_only or no_degree):
        return base
    words = _filter_words(base, country, language, radius)
    if date_posted and date_posted != "any":
        parts.append(words["date_posted"][DATE_POSTED.index(date_posted) - 1])
    if job_type:
        parts.append(words["job_type"][JOB_TYPES.index(job_type)])
    if remote_only:
        parts.append(words["remote"])
    if no_degree:
        parts.append(words["no_degree"])
    return " ".join(parts)


def _results_link(query, country, language):
    return f"{P.SITE}/search?" + urlencode({"q": query, "udm": 8, "hl": language, "gl": country.lower()},
                                           quote_via=quote_plus)


# ---- memo ---------------------------------------------------------------------------------------------------

def _page_key(query, country, language, radius, page):
    return {"q": query, "country": country, "language": language, "radius": radius, "page": page}


def _remember(parsed, query, country, language, radius, page):
    """Memoise each job's viewer token + query and the next page's token
    (in-process now, database in the background)."""
    job_ttl = timedelta(days=config.GOOGLE_JOBS_JOB_MEMO_DAYS)
    page_ttl = timedelta(hours=config.GOOGLE_JOBS_PAGE_MEMO_HOURS)
    writes = []
    for job in parsed["jobs"]:
        token = parsed["detail_tokens"].get(job["id"])
        if token:
            writes.append((NS_JOB, {"id": job["id"]}, {"query": query, "token": token, "country": country,
                                                       "language": language, "is_remote": job["is_remote"]}, job_ttl))
    if parsed.get("next_page_token"):
        writes.append((NS_PAGE, _page_key(query, country, language, radius, page + 1), parsed["next_page_token"], page_ttl))

    def flush():
        for ns, key, value, ttl in writes:
            fetch.memo.put(ns, key, value, ttl)
    _memo_writer.submit(flush)


# ---- search -------------------------------------------------------------------------------------------------

def _walk(query, first, last, country, language, radius):
    """Google pages first..last of `query` -> ([(page, parsed)], has_more).
    Starts from the nearest memoised next-page token (page 1 = the results
    page) and chains the next-page callback."""
    start, token = first, None
    while start > 1:
        token = fetch.memo.get(NS_PAGE, _page_key(query, country, language, radius, start))
        if token:
            break
        start -= 1
    text = fetch.next_page(token, country=country, language=language) if start > 1 else None
    if start > 1 and text is None:          # the memoised token was rejected: walk from page 1
        start = 1
    if start == 1:
        text = fetch.results_page(query, country=country, language=language, radius=radius)
    out, page, has_more = [], start, False
    while text is not None:
        parsed = P.parse_results(text, query=query, country=country, language=language)
        _remember(parsed, query, country, language, radius, page)
        if page >= first:
            out.append((page, parsed))
        has_more = bool(parsed["next_page_token"] and parsed["jobs"])
        if page >= last or not has_more:
            break
        page += 1
        text = fetch.next_page(parsed["next_page_token"], country=country, language=language)
    return out, has_more and last < config.GOOGLE_JOBS_MAX_PAGES


def _search(query, country, language, radius, page, num_pages, keep=None):
    first = (page - 1) * num_pages + 1
    last = min(page * num_pages, config.GOOGLE_JOBS_MAX_PAGES)
    pages, has_more = _walk(query, first, last, country, language, radius)
    jobs, seen = [], set()
    for _, parsed in pages:
        for job in parsed["jobs"]:
            if job["id"] in seen or (keep and not keep(job)):
                continue
            seen.add(job["id"])
            job["position"] = (first - 1) * PAGE_SIZE + len(jobs) + 1
            jobs.append(job)
    return jobs, has_more


def search(query, location=None, country="US", language="en", date_posted=None, job_type=None, remote_only=None,
           no_degree=None, radius=None, page=1, num_pages=1):
    """Google for Jobs results for a query: 10 jobs per Google page,
    `num_pages` Google pages per response page."""
    q = build_query(query, location, country, language, date_posted, job_type, remote_only, no_degree, radius)
    jobs, has_more = _search(q, country, language, radius, page, num_pages)
    return paged_result("jobs", jobs, page, PAGE_SIZE * num_pages, has_more=has_more,
                        search_information={"query": q, "link": _results_link(q, country, language)})


def _name_key(name):
    """'Capital One, N.A.' / 'CAPITAL ONE' -> 'capital one' (legal suffixes dropped)."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    drop = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "gmbh", "ag", "sa", "na",
            "the", "group", "holdings", "careers", "usa", "us"}
    return " ".join(w for w in words if w not in drop)


def company_jobs(company, location=None, country="US", language="en", date_posted=None, job_type=None,
                 remote_only=None, page=1, num_pages=1):
    """Open jobs at one employer: Google's "<company> jobs" results kept to
    listings whose employer matches the name."""
    want = _name_key(company)

    def keep(job):
        have = _name_key(job["company"]["name"])
        return bool(want) and bool(have) and (have == want or have.startswith(want + " ") or want.startswith(have + " "))
    q = build_query(f"{company} jobs", location, country, language, date_posted, job_type, remote_only, None, None)
    jobs, has_more = _search(q, country, language, None, page, num_pages, keep=keep)
    return paged_result("jobs", jobs, page, PAGE_SIZE * num_pages, has_more=has_more,
                        search_information={"query": q, "company": company, "link": _results_link(q, country, language)})


# ---- details ------------------------------------------------------------------------------------------------

def _resolve_company_links(job):
    company = job.get("company") or {}
    links = [company.get("website")] + [r.get("link") for r in company.get("ratings") or []]
    links = [link for link in links if link and "/goto?" in link]
    if not links:
        return job
    resolved = dict(zip(links, (P.strip_tracking(r) if r and "/goto?" not in r else None for r in
                                fetch.run_parallel_quiet([lambda link=link: resolve_goto(link) for link in links]))))
    if company.get("website"):
        company["website"] = resolved.get(company["website"]) or company["website"]
    for rating in company.get("ratings") or []:
        rating["link"] = resolved.get(rating["link"]) or rating["link"]
    return job


def details(job, country="US", language="en"):
    """One job with its full description, highlights, apply options and the
    employer's website + ratings. `job` is {"id", "query"} (schemas)."""
    job_id = job["id"]
    ref = fetch.memo.get(NS_JOB, {"id": job_id}) or {}
    query = job.get("query") or ref.get("query")
    out, card = None, None
    if ref.get("token"):
        text = fetch.viewer(ref["token"], country=country, language=language)
        out = P.parse_details(text, query=query, country=country, language=language) if text else None
        if out and out["id"] != job_id:
            out = None
    if out is None:
        if not query:
            raise fetch.GoogleNotFound(f"job {job_id} is unknown here: pass its `link` from /google-jobs/search "
                                       f"(the link carries the search it came from)")
        html = fetch.results_page(query, country=country, language=language, job_id=job_id, label="job")
        parsed = P.parse_results(html, query=query, country=country, language=language)
        _remember(parsed, query, country, language, None, 1)
        card = next((j for j in parsed["jobs"] if j["id"] == job_id), None)
        if card is None:
            raise fetch.GoogleNotFound(f"Google does not list job {job_id} for the search '{query}': the posting "
                                       f"expired, or the link's search never contained it (use the `link` of a "
                                       f"/google-jobs/search result)")
        token = parsed["detail_tokens"].get(job_id)
        text = fetch.viewer(token, country=country, language=language) if token else None
        out = P.parse_details(text, query=query, country=country, language=language) if text else None
        if out is None:          # the viewer failed: the card holds the same job fields
            out = {k: v for k, v in card.items() if k != "position"}
            out["company"].update({"website": None, "domain": None, "ratings": []})
    # "Work from home" is a card chip only; the viewer does not repeat it
    if (card or ref).get("is_remote"):
        out["is_remote"] = True
    out["link"] = P.job_link(job_id, query)
    return _resolve_company_links(out)


def batch(jobs, country="US", language="en"):
    """Up to 10 jobs in parallel; ids Google no longer lists (or that are
    unknown and came without a link) are listed in not_found."""
    errors = {}

    def one(job):
        def call():
            try:
                return details(job, country=country, language=language)
            except fetch.GoogleNotFound:
                return None
            except Exception as e:
                errors[job["id"]] = e
                return None
        return call
    with ThreadPoolExecutor(max_workers=min(config.GOOGLE_JOBS_BATCH_WORKERS, len(jobs))) as pool:
        results = list(pool.map(lambda f: f(), [one(j) for j in jobs]))
    if errors and len(errors) == len(jobs):
        raise next(iter(errors.values()))
    found = [r for r in results if r]
    return {"jobs": found, "not_found": [j["id"] for j, r in zip(jobs, results) if not r and j["id"] not in errors],
            "failed": [{"id": k, "error": f"{type(e).__name__}: {e}"} for k, e in errors.items()]}


# ---- suggestions --------------------------------------------------------------------------------------------

def autocomplete(query, country="US", language="en", limit=10):
    """Job-search suggestions for a partial title: Google's suggestions for
    '<query> jobs' (the jobs client alone answers web suggestions like
    'nurse shark')."""
    prefix = query if re.search(r"\bjobs?\b", query, re.I) else f"{query} jobs"
    raw = gs_autocomplete.autocomplete(prefix, client="google", country=country, language=language, limit=20)
    items = []
    for s in raw["suggestions"]:
        value = s.get("text")
        if value and value not in items:
            items.append(value)
    items = items[:limit]
    return {"query": query, "count": len(items),
            "suggestions": [{"position": i + 1, "text": t, "link": _results_link(t, country, language)}
                            for i, t in enumerate(items)]}
