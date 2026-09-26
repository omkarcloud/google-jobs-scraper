"""Live endpoint smoke tests: one call per /google-jobs/* route against a
running service, with example values proven to return data (2026-09-26).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless GOOGLE_JOBS_BASE points at a running service:

    SCRAPERS_PORT=6049 ONLY_SCRAPER=google-jobs python run.py
    GOOGLE_JOBS_BASE=http://127.0.0.1:6049 python -m pytest google_jobs/test_endpoints.py -q

Results pages and callbacks run on minted SERP identities (a headed
Camoufox + the CapSolver extension, 30-240 s for the first one), so the
first call is slow.
"""
import os

import pytest

BASE = os.environ.get("GOOGLE_JOBS_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set GOOGLE_JOBS_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=600)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=600).status_code


def test_search():
    body = call("/google-jobs/search", query="data analyst jobs", location="Chicago, IL")
    jobs = body["jobs"]
    assert len(jobs) >= 8 and body["current_page"] == 1 and body["next"]
    job = jobs[0]
    assert job["id"] and job["title"] and job["company"]["name"] and job["apply_options"] and job["description"]
    assert job["link"].startswith("https://www.google.com/search?") and "htidocid=" in job["link"]
    body = call("/google-jobs/search", query="software engineer", location="Austin, TX", job_type="full_time",
                date_posted="week", page="2", num_pages="2")
    assert body["current_page"] == 2 and body["per_page"] == 20 and len(body["jobs"]) >= 10
    assert body["jobs"][0]["position"] == 21
    assert sum("full_time" in j["job_types"] for j in body["jobs"]) >= len(body["jobs"]) * 0.7


def test_search_remote_and_language():
    body = call("/google-jobs/search", query="customer support", remote_only="true")
    assert sum(j["is_remote"] for j in body["jobs"]) >= len(body["jobs"]) * 0.7
    body = call("/google-jobs/search", query="softwareentwickler jobs berlin", country="DE", language="de")
    assert body["jobs"] and body["jobs"][0]["location"]["display_name"]


def test_details():
    job = call("/google-jobs/search", query="registered nurse jobs", location="Denver")["jobs"][0]
    body = call("/google-jobs/details", job=job["link"])
    assert body["id"] == job["id"] and body["description_html"] and body["apply_options"]
    assert "ratings" in body["company"] and "website" in body["company"]
    assert call("/google-jobs/details", job=job["id"])["id"] == job["id"]      # the id alone works once searched


def test_details_batch():
    jobs = call("/google-jobs/search", query="accountant jobs", location="New York")["jobs"][:3]
    body = call("/google-jobs/details/batch", jobs=",".join(j["id"] for j in jobs))
    assert len(body["jobs"]) == 3 and body["not_found"] == []


def test_company_jobs():
    body = call("/google-jobs/company-jobs", company="Capital One")
    assert body["jobs"] and all("capital one" in j["company"]["name"].lower() for j in body["jobs"])


def test_autocomplete():
    body = call("/google-jobs/autocomplete", query="data anal")
    assert body["count"] >= 5 and all("job" in s["text"] for s in body["suggestions"])


def test_errors():
    assert status("/google-jobs/details", job="not a job") == 400
    assert status("/google-jobs/search", query="x", page="20", num_pages="2") == 400
    assert status("/google-jobs/details", job="AAAAAAAAAAAAAAAAAAAAAA==") == 404
