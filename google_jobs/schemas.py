"""Marshmallow request schemas for every /google-jobs/* route.

Generic fields come from the shared schema_fields.py and the Google Search
schemas (country / language / query-or-link); this module adds the job
references. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url` / `id` pair): `query` takes a search term OR a
google.com/search link (whose gl / hl fill country / language when those
are absent), `job` a job id OR a Google Jobs link, `jobs` a comma list of
either, `company` a name OR a google.com/search link naming it.
"""
from marshmallow import ValidationError, fields, post_load, pre_load, validate

import config
from google_jobs import jobs as J, refs
from google_search.schemas import CountryField, LanguageField, SearchQueryField
from schema_fields import BaseSchema, ChoiceField, Flag, LimitField, PageField, PositiveInt, QueryField, RefField, StrippedString

MAX_BATCH = 10


class JobRefField(RefField):
    resolver = staticmethod(refs.resolve_job)


class CompanyRefField(RefField):
    resolver = staticmethod(refs.resolve_company)

    def __init__(self, **kwargs):
        kwargs.setdefault("validate", validate.Length(min=1, max=100))
        super().__init__(**kwargs)


class JobListField(fields.Field):
    """'id1,id2,<google jobs link>' -> [{"id", "query"}, …] (resolved,
    deduped by id, 1..MAX_BATCH)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out, ids = [], set()
        for item in refs.split_jobs(value):
            try:
                ref = refs.resolve_job(item)
            except ValueError as e:
                raise ValidationError(f"'{item[:80]}': {e}")
            if ref["id"] not in ids:
                ids.add(ref["id"])
                out.append(ref)
        if not out:
            raise ValidationError("Must list at least one job id or Google Jobs link (comma-separated).")
        if len(out) > MAX_BATCH:
            raise ValidationError(f"At most {MAX_BATCH} jobs.")
        return out


class LocationText(StrippedString):
    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=100))
        super().__init__(**kwargs)


class _Locale(BaseSchema):
    country = CountryField()
    language = LanguageField()

    @pre_load
    def from_link(self, data, **kwargs):
        """A pasted google.com link fills country / language."""
        link_params = {}
        for key in ("query", "company", "job"):
            link_params = refs.params_of(data.get(key) or "")
            if link_params:
                break
        if not link_params:
            return data
        data = dict(data)
        if link_params.get("gl") and not data.get("country"):
            data["country"] = link_params["gl"]
        if link_params.get("hl") and not data.get("language"):
            data["language"] = link_params["hl"].split("-")[0]
        return data


class _Filters(_Locale):
    location = LocationText()
    date_posted = ChoiceField(J.DATE_POSTED, load_default=None)
    job_type = ChoiceField(J.JOB_TYPES, load_default=None)
    remote_only = Flag()
    page = PageField(max_page=config.GOOGLE_JOBS_MAX_PAGES)
    num_pages = PositiveInt(max_value=J.MAX_NUM_PAGES, load_default=1)

    @post_load
    def depth(self, data, **kwargs):
        if (data["page"] - 1) * data["num_pages"] + 1 > config.GOOGLE_JOBS_MAX_PAGES:
            raise ValidationError({"page": [f"Google lists at most {config.GOOGLE_JOBS_MAX_PAGES * J.PAGE_SIZE} jobs "
                                            f"per search: page x num_pages must stay within "
                                            f"{config.GOOGLE_JOBS_MAX_PAGES} Google pages."]})
        return data


class SearchSchema(_Filters):
    query = SearchQueryField()
    no_degree = Flag()
    radius = PositiveInt(max_value=500)


class CompanyJobsSchema(_Filters):
    company = CompanyRefField()


class JobSchema(_Locale):
    job = JobRefField()


class JobBatchSchema(_Locale):
    jobs = JobListField()


class AutocompleteSchema(_Locale):
    query = QueryField(max_length=100)
    limit = LimitField(default=10, max_size=20)
