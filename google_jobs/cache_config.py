"""Cache TTL per /google-jobs/* endpoint (cache.py, keyed on the validated
params — marshmallow fills the defaults, so `?page=1` and no `page` share
a row, and a job's id-form / link-form share a row only when they resolve
to the same {id, query}).

Results pages cost an identity use each and listings turn over within
days, so searches cache for a few hours; a posting's text rarely changes
once published; suggestions barely move."""
from datetime import timedelta

SEARCH_CACHE = timedelta(hours=3)
COMPANY_JOBS_CACHE = timedelta(hours=3)
DETAILS_CACHE = timedelta(hours=12)
AUTOCOMPLETE_CACHE = timedelta(hours=12)
