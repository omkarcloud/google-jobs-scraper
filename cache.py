"""The two names google_jobs/fetch.py uses from a response cache. This kit runs
without a database: storage() is None, so the job / page memo falls back to
the local SQLite file (config.GOOGLE_MEMO_SQLITE_PATH)."""
import json


class PostgresResponseCache:
    @staticmethod
    def canonical(data):
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def storage():
    return None
