"""
Optional shared cache in Upstash Redis, reached over its REST API.

The in-memory result cache in main.py is per server instance and starts
empty on every Vercel cold start. With UPSTASH_REDIS_REST_URL and
UPSTASH_REDIS_REST_TOKEN set (Vercel's Upstash integration names them
KV_REST_API_URL and KV_REST_API_TOKEN, which also work), every instance
shares one cache, so a search anyone has run lately is answered at once.

Nothing here may slow or break a search: calls time out quickly, and after a
failure the cache is skipped for a while and searches use memory only.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

KEY_PREFIX = "vistora:"
POPULAR_KEY = "popular"
POPULAR_KEEP = 500  # most-searched queries to remember

TIMEOUT_SECONDS = 1.5
BACKOFF_SECONDS = 30

# One connection pool, and a small pool so writes never delay a response.
_session = requests.Session()
_writes = ThreadPoolExecutor(max_workers=2)
_down_until = 0.0


def _config():
    url = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN")
    return (url.rstrip("/"), token) if url and token else None


def enabled() -> bool:
    return _config() is not None


def command(*args):
    """Run one Redis command; its result, or None if unavailable or failed."""
    global _down_until

    config = _config()
    if config is None or time.monotonic() < _down_until:
        return None

    url, token = config
    try:
        response = _session.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=list(args),
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(body["error"])
        return body.get("result")
    except Exception as exc:
        _down_until = time.monotonic() + BACKOFF_SECONDS
        print(f"Shared cache unavailable, using memory only: {exc}")
        return None


def health():
    """
    Whether the shared cache is working, for the status check: None when it is
    not set up, else {"ok", "detail", "ms"}. It pings Redis directly (ignoring
    the pause after a failure) and never includes the address or token.
    """
    config = _config()
    if config is None:
        return None

    url, token = config
    started = time.perf_counter()
    try:
        response = _session.post(
            url, headers={"Authorization": f"Bearer {token}"}, json=["PING"], timeout=TIMEOUT_SECONDS
        )
    except Exception as exc:
        return {"ok": False, "detail": f"not reachable ({type(exc).__name__})", "ms": None}

    milliseconds = round((time.perf_counter() - started) * 1000)
    if response.status_code in (401, 403):
        return {"ok": False, "detail": f"the token was rejected (HTTP {response.status_code})", "ms": milliseconds}
    try:
        response.raise_for_status()
        ok = response.json().get("result") == "PONG"
    except Exception:
        return {"ok": False, "detail": f"unexpected answer (HTTP {response.status_code})", "ms": milliseconds}
    return {"ok": ok, "detail": "working" if ok else "unexpected answer", "ms": milliseconds}


def get(key):
    """The JSON value stored under key, or None."""
    raw = command("GET", KEY_PREFIX + key)
    if raw is None:
        return None

    try:
        return json.loads(raw)
    except ValueError:
        return None


def put(key, value, ttl_seconds, wait=False) -> bool:
    """Store value (JSON) under key for ttl_seconds, in the background unless wait."""
    try:
        raw = json.dumps(value)
    except (TypeError, ValueError):
        return False

    job = _writes.submit(command, "SET", KEY_PREFIX + key, raw, "EX", int(ttl_seconds))
    return job.result() == "OK" if wait else True


def count_query(query):
    """Count one search of query, so the most-searched ones can be kept warm."""
    if enabled():
        _writes.submit(command, "ZINCRBY", KEY_PREFIX + POPULAR_KEY, 1, query)


def top_queries(limit):
    """The most-searched queries, most popular first; also trims old tail entries."""
    if limit <= 0:
        return []

    queries = command("ZREVRANGE", KEY_PREFIX + POPULAR_KEY, 0, limit - 1) or []
    command("ZREMRANGEBYRANK", KEY_PREFIX + POPULAR_KEY, 0, -(POPULAR_KEEP + 1))
    return [query for query in queries if isinstance(query, str)]


# --------------------------------------------------
# Cache statistics: how many searches the cache answered
# --------------------------------------------------

STATS_KEEP_DAYS = 10
STATS_KINDS = ("memory_hit", "shared_hit", "miss")


def _day(offset=0):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - offset * 86400))


def record(kind):
    """Count one cache outcome ("memory_hit", "shared_hit" or "miss") for today, in the background."""
    if kind in STATS_KINDS and enabled():
        _writes.submit(_count, kind)


def _count(kind):
    key = f"{KEY_PREFIX}stats:{_day()}"
    command("HINCRBY", key, kind, 1)
    command("EXPIRE", key, STATS_KEEP_DAYS * 86400)


def stats(days=7):
    """
    Cache outcomes for today and the last `days` days, or None when the shared
    cache is not set up. {"today": {...}, "week": {...}} with the three counts,
    "searches" and "hit_rate" (None when there were no searches).
    """
    if not enabled():
        return None

    def read(offset):
        raw = command("HGETALL", f"{KEY_PREFIX}stats:{_day(offset)}") or []
        if isinstance(raw, list):
            pairs = dict(zip(raw[0::2], raw[1::2]))
        else:
            pairs = raw if isinstance(raw, dict) else {}
        return {kind: int(pairs.get(kind, 0)) for kind in STATS_KINDS}

    def summarise(rows):
        total = {kind: sum(row[kind] for row in rows) for kind in STATS_KINDS}
        searches = sum(total.values())
        hits = total["memory_hit"] + total["shared_hit"]
        return {**total, "searches": searches, "hit_rate": round(hits / searches, 3) if searches else None}

    rows = [read(offset) for offset in range(days)]
    return {"today": summarise(rows[:1]), "week": summarise(rows)}
