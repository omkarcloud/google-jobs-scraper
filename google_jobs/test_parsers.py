"""Offline tests for google_jobs: parsers, markup extraction, references,
schemas and the query builder against captured responses
(google_jobs/fixtures/*.gz, 2026-09-24/26):

  serp.html          results page, "data analyst jobs chicago" (hl=en, gl=us)
  page2.txt          its next-page callback chunk (/async/callback:550)
  serp_de.html       "softwareentwickler jobs berlin" (hl=de, gl=de)
  serp_gb.html       "software engineer jobs london" (gl=gb)
  detail.txt         viewer (/async/callback:8166) of the page's first job
  detail_de.txt      the same viewer with hl=de (other layout, no highlights)
  detail_ratings.txt viewer with employer ratings
  detail_website.txt viewer with the employer website (browser capture)
  detail_error.txt   HTTP 500 body (callback without a token)
  stub.txt           the refusal stub a callback answers without identity cookies

    cd scrapers && python -m pytest google_jobs/test_parsers.py -q
"""
import gzip
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_jobs import markup, parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def load(name):
    with gzip.open(os.path.join(FX, name + ".gz"), "rt", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---- markup ------------------------------------------------------------------------------------------

def test_chunk_status_and_refusal():
    assert markup.is_refused(load("stub.txt"))
    assert markup.chunk_status(load("page2.txt"))[0] != 3     # served: [4,…] or [7,…]; refused: [3,…]
    assert not markup.is_refused(load("page2.txt"))
    assert markup.chunk_status(load("serp.html")) is None


def test_jsdata_both_shapes():
    page = markup.JsData(load("serp.html"))          # object literal "KEY":[…]
    chunk = markup.JsData(load("page2.txt"))         # frame [[["KEY","<json>"]…]]
    doc = P.parse_document(load("serp.html"))
    card = doc.cssselect("div.EimVGf[data-share-url]")[0]
    assert page.ref(card, "UmMWcb")[9] == "rE71TFwWpTWbd28uAAAAAA=="
    doc2 = P.parse_document(load("page2.txt"))
    card2 = doc2.cssselect("div.EimVGf[data-share-url]")[0]
    assert chunk.ref(card2, "UmMWcb")[9] == "oFjnZuF7vkkimPKaAAAAAA=="


def test_filter_links_and_suffixes():
    labels = [label for label, _ in markup.filter_links(load("serp.html"))]
    assert labels[:5] == ["Yesterday", "Last 3 days", "Last week", "Last month", "Date posted"]
    words = P.filter_suffixes(load("serp.html"), "data analyst jobs chicago")
    assert words["date_posted"] == ["since yesterday", "in the last 3 days", "in the last week", "in the last month"]
    assert words["job_type"] == ["full time", "part time", "contract", "internship"]
    assert words["remote"] == "remote" and words["no_degree"] == "no degree"
    de = P.filter_suffixes(load("serp_de.html"), "softwareentwickler jobs berlin")
    assert de["job_type"] == ["Vollzeit", "Teilzeit", "Vertrag", "Praktikum"]
    assert de["remote"] == "Homeoffice"


# ---- results ----------------------------------------------------------------------------------------

def test_results_page():
    out = P.parse_results(load("serp.html"), now=NOW)
    assert out["query"] == "data analyst jobs chicago"
    assert len(out["jobs"]) == 10 and len(out["detail_tokens"]) == 10 and out["next_page_token"]
    first = out["jobs"][0]
    assert list(first)[:4] == ["position", "id", "title", "link"]
    assert first["id"] == "rE71TFwWpTWbd28uAAAAAA=="
    assert first["title"] == "Full-Time Data Science Associate"
    assert first["link"] == "https://www.google.com/search?q=data+analyst+jobs+chicago&udm=8&htidocid=rE71TFwWpTWbd28uAAAAAA%3D%3D"
    assert first["apply_link"].startswith("https://www.linkedin.com/jobs/view/") and "utm_" not in first["apply_link"]
    assert first["job_types"] == ["full_time"] and first["date_posted"] == "2026-09-26" and first["posted_ago"] == "12 hours ago"
    assert first["company"]["name"] == "RoShay Services" and first["company"]["logo"].startswith("https://")
    assert first["location"] == {"display_name": "Chicago, IL", "city": "Chicago", "region": "IL", "country": None,
                                 "google_maps_link": "https://www.google.com/maps/place/?ftid=0x880e2c3cd0f4cbed:0xafe0a6ad09c0c000"}
    assert first["source"] == "LinkedIn"
    assert first["occupation"] == {"onet_code": "15-1111.00", "onet_job_zone": 5}
    assert first["description"].startswith("Role Overview:") and "\n\n• " in first["description"]
    assert [h["title"] for h in first["highlights"]] == ["Qualifications", "Responsibilities"]
    assert first["highlights"][0]["more_count"] == 2
    capital_one = out["jobs"][2]
    assert capital_one["salary"] == {"min": 101000, "max": 127000, "currency": "USD", "period": "year",
                                     "text": "$101K–$127K a year"}
    assert capital_one["company"]["id"] == "/m/04c_q_"
    assert capital_one["company"]["link"] == "https://www.google.com/search?kgmid=/m/04c_q_"
    assert capital_one["benefits"] == ["health_insurance"]
    assert len(capital_one["apply_options"]) == 8 and capital_one["apply_options"][0] == {
        "source": "Built In Chicago", "domain": "builtinchicago.org",
        "link": "https://www.builtinchicago.org/job/sr-data-analyst/11268222", "is_direct": False}
    remote = out["jobs"][1]
    assert remote["is_remote"] is True and remote["mentions_degree"] is False and remote["job_types"] == ["contractor"]
    assert out["jobs"][7]["location"]["region"] == "IL"            # "Chicago, IL (+4 others)"
    assert out["jobs"][7]["job_types"] == ["full_time", "part_time"]


def test_next_page_chunk():
    out = P.parse_results(load("page2.txt"), query="data analyst jobs chicago", now=NOW)
    assert out["query"] == "data analyst jobs chicago"       # chunks carry no query: the caller's is kept
    assert len(out["jobs"]) == 10 and out["next_page_token"]
    assert out["jobs"][0]["title"] == "Data Analyst – Mid/Back Office Tech Team"
    assert out["jobs"][0]["salary"]["min"] == 80000
    assert all(j["description"] and j["apply_options"] for j in out["jobs"])


def test_german_page():
    out = P.parse_results(load("serp_de.html"), country="DE", language="de", now=NOW)
    job = out["jobs"][1]
    assert job["salary"] == {"min": 54000, "max": 93000, "currency": "EUR", "period": "year",
                             "text": "54.000 € bis 93.000 € pro Jahr"}
    assert out["jobs"][2]["job_types"] == ["full_time", "part_time"]
    assert out["jobs"][2]["benefits"] == ["retirement_plan"]
    assert out["jobs"][5]["is_remote"] is True                  # "Beliebiger Ort" + Homeoffice chip


def test_uk_day_rate():
    out = P.parse_results(load("serp_gb.html"), country="GB", now=NOW)
    job = out["jobs"][3]
    assert job["salary"]["currency"] == "GBP" and job["salary"]["period"] == "day"
    assert (job["salary"]["min"], job["salary"]["max"]) == (600, 800)


def test_empty_and_garbage():
    assert P.parse_results("", query="x")["jobs"] == []
    assert P.parse_results(load("stub.txt"), query="x") == {"query": "x", "jobs": [], "detail_tokens": {},
                                                            "next_page_token": None}
    assert P.parse_details(load("stub.txt")) is None
    assert P.parse_details(load("detail_error.txt")) is None


# ---- viewer -----------------------------------------------------------------------------------------

def test_details():
    job = P.parse_details(load("detail.txt"), query="data analyst jobs chicago", now=NOW)
    assert job["id"] == "rE71TFwWpTWbd28uAAAAAA==" and job["title"] == "Full-Time Data Science Associate"
    assert job["description_html"].startswith("<") and job["description"]
    assert job["company"]["ratings"] == [] and job["company"]["website"] is None
    assert [a["source"] for a in job["apply_options"]] == ["LinkedIn", "BeBee"]


def test_details_ratings_and_direct_apply():
    job = P.parse_details(load("detail_ratings.txt"), query="q", now=NOW)
    assert job["company"]["id"] == "/g/11g9n69f7f"
    assert [(r["source"], r["rating"], r["review_count"]) for r in job["company"]["ratings"]] == [
        ("Glassdoor", 4.3, 29), ("Indeed", 4.8, 5), ("AmbitionBox", 4.1, 5)]
    assert all(r["link"].startswith("https://www.google.com/goto?url=") for r in job["company"]["ratings"])
    assert [a["is_direct"] for a in job["apply_options"]] == [False, True, False, False]
    assert job["mentions_degree"] is False and job["job_types"] == ["contractor"]


def test_details_website_and_big_counts():
    job = P.parse_details(load("detail_website.txt"), query="q", now=NOW)
    assert job["company"]["domain"] == "homedepot.com"
    assert job["company"]["website"].startswith("https://www.google.com/goto?url=")
    assert job["company"]["ratings"][0]["review_count"] == 70600


def test_details_other_language_layout():
    job = P.parse_details(load("detail_de.txt"), query="q", country="US", language="de", now=NOW)
    assert job["apply_options"] and job["apply_options"][0]["source"] == "LinkedIn"
    assert job["posted_ago"] == "vor 12 Stunden" and job["date_posted"] == "2026-09-26"
    assert job["location"]["country"] == "Vereinigte Staaten"


# ---- values -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,country,language,expected", [
    ("$65–$75 an hour", "US", "en", (65, 75, "USD", "hour")),
    ("$68,911–$161,544 a year", "US", "en", (68911, 161544, "USD", "year")),
    ("€50.000 par an", "FR", "fr", (50000, 50000, "EUR", "year")),
    ("12,50 € pro Stunde", "DE", "de", (12.5, 12.5, "EUR", "hour")),
    ("₹3L–₹5L a year", "IN", "en", (300000, 500000, "INR", "year")),
    ("$70K a year", "CA", "en", (70000, 70000, "CAD", "year")),
    ("USA 87–USA 91 an hour", "US", "en", (87, 91, "USD", "hour")),
])
def test_salary(text, country, language, expected):
    s = P.parse_salary(text, country, language)
    assert (s["min"], s["max"], s["currency"], s["period"]) == expected


def test_ages_and_types():
    assert P.parse_age("30+ days ago", NOW) == "2026-08-27"
    assert P.parse_age("il y a 1 semaine", NOW) == "2026-09-19"
    assert P.parse_age("Full-time", NOW) is None
    assert P.job_types("Vollzeit und Teilzeit") == ["full_time", "part_time"]
    assert P.job_types("Full–time") == ["full_time"]
    assert P.strip_tracking("https://x.com/j?id=1&utm_source=google_jobs_apply&utm_medium=organic") == "https://x.com/j?id=1"
    # the viewer serves ratings / website links either direct (with utm_*) or as /goto wrappers
    assert P._outbound("https://www.indeed.com/cmp/Cdw/reviews?utm_campaign=google_jobs_reviews&fcountry=ALL") == \
        "https://www.indeed.com/cmp/Cdw/reviews?fcountry=ALL"
    assert P._outbound("/goto?url=X") == "https://www.google.com/goto?url=X"


# ---- references --------------------------------------------------------------------------------------

def test_job_refs():
    assert refs.resolve_job("rE71TFwWpTWbd28uAAAAAA==") == {"id": "rE71TFwWpTWbd28uAAAAAA==", "query": None}
    assert refs.resolve_job("vt=20/docid=rE71TFwWpTWbd28uAAAAAA==")["id"] == "rE71TFwWpTWbd28uAAAAAA=="
    share = ("https://www.google.com/search?ibp=htl;jobs&q=data+analyst+jobs+chicago&htidocid=UfrJTBe-N-f2XRZ8AAAAAA%3D%3D"
             "&hl=en-US&shem=epsd1,rimspwouoe#fpstate=tldetail&htivrt=jobs")
    assert refs.resolve_job(share) == {"id": "UfrJTBe-N-f2XRZ8AAAAAA==", "query": "data analyst jobs chicago"}
    vhid = "https://www.google.com/search?q=jobs&udm=8#vhid=vt%3D20/docid%3DPjUC9oZVlnm8rP7DAAAAAA%3D%3D&vssid=x"
    assert refs.resolve_job(vhid)["id"] == "PjUC9oZVlnm8rP7DAAAAAA=="
    with pytest.raises(ValueError):
        refs.resolve_job("https://www.linkedin.com/jobs/view/1")
    assert refs.split_jobs(f"a1b2c3d4e5f6g7h8i9j0kk==, {share}, rE71TFwWpTWbd28uAAAAAA==")[1] == share
    assert refs.resolve_company("https://www.google.com/search?q=Jobs+at+The+Home+Depot") == "The Home Depot"
    assert refs.resolve_company("Stripe jobs") == "Stripe"


def test_query_builder_english():
    from google_jobs import jobs as J
    q = J.build_query("data analyst", "Chicago, IL", date_posted="week", job_type="internship", remote_only=True,
                      no_degree=True)
    assert q == "data analyst Chicago, IL in the last week internship remote no degree"
    assert J.build_query("nurse jobs") == "nurse jobs"
    assert J._name_key("Capital One, Inc.") == J._name_key("CAPITAL ONE") == "capital one"
