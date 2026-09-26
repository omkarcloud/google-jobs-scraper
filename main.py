"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See README.md for every endpoint.
"""
import json
import os

from google_jobs import jobs, refs

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # Google for Jobs results: full description, salary, apply links from every job board, company, location
    found = jobs.search("software engineer", location="San Francisco, CA")
    save("search_software_engineer_san_francisco.json", found)

    # one job in full: description HTML, highlights, every apply option, employer ratings and website
    if found["jobs"]:
        save("job_details.json", jobs.details(refs.resolve_job(found["jobs"][0]["link"])))

    # every open job at one company
    save("company_jobs_spacex.json", jobs.company_jobs("SpaceX"))
