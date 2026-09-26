"""The 5 Google Jobs endpoints. Every path is served with and without the
`/google-jobs` prefix, so code generated against the hosted API on
RapidAPI (paths like /search) runs unchanged against this server.

Params are validated by the marshmallow schemas in google_jobs/schemas.py
(the same ones the hosted API uses); failures map to HTTP like this:
bad params -> 400, not found -> 404, Google blocked / upstream error -> 502,
anything else -> 500.
"""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from google_jobs import jobs, schemas
from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

PREFIX = "/google-jobs"

# (public path, schema, function, paginated) — in the order of the docs
ENDPOINTS = [
    ("/search", schemas.SearchSchema, jobs.search, True),
    ("/details", schemas.JobSchema, jobs.details, False),
    ("/details/batch", schemas.JobBatchSchema, jobs.batch, False),
    ("/company-jobs", schemas.CompanyJobsSchema, jobs.company_jobs, True),
    ("/autocomplete", schemas.AutocompleteSchema, jobs.autocomplete, False),
]


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw_params):
    """Flat pagination (count / per_page / current_page / total_pages / next /
    previous first), links rebuilt from the caller's own params."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw_params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def handle(path, schema_cls, impl, paginated):
    label = f"google-jobs {path.strip('/')}"
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"google-jobs rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"google-jobs blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"{label} failed: {e}"}, 502)
    except Exception as e:
        return json_response({"error": f"{label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


def mount(path, schema_cls, impl, paginated):
    """Serve one endpoint at /path and /google-jobs/path."""
    def handler():
        return handle(path, schema_cls, impl, paginated)
    handler.__name__ = "google_jobs_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/")
@route("/health")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
