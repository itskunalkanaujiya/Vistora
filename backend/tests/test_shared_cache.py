import json

import pytest
from fastapi.testclient import TestClient

import main
import search_credits
import shared_cache

client = TestClient(main.app)


class FakeRedis:
    """Stands in for the Upstash REST endpoint: one JSON command per POST."""

    def __init__(self):
        self.data = {}
        self.scores = {}
        self.commands = []
        self.fail = False

    def post(self, url, headers=None, json=None, timeout=None):
        self.commands.append(json)
        if self.fail:
            raise OSError("redis is down")

        name, *args = json
        if name == "GET":
            result = self.data.get(args[0])
        elif name == "SET":
            self.data[args[0]] = args[1]
            result = "OK"
        elif name == "ZINCRBY":
            self.scores[args[2]] = self.scores.get(args[2], 0) + args[1]
            result = str(self.scores[args[2]])
        elif name == "ZREVRANGE":
            ranked = sorted(self.scores, key=self.scores.get, reverse=True)
            result = ranked[: args[2] + 1]
        else:
            result = 0
        return FakeResponse({"result": result})


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class _SameThread:
    """Runs background writes at once, so assertions can follow immediately."""

    def submit(self, fn, *args):
        result = fn(*args)

        class Done:
            def result(self_inner):
                return result

        return Done()


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://redis.example.com")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "token")
    monkeypatch.setattr(shared_cache, "_session", fake)
    monkeypatch.setattr(shared_cache, "_down_until", 0.0)
    monkeypatch.setattr(shared_cache, "_writes", _SameThread())
    return fake


@pytest.fixture(autouse=True)
def fresh_credits():
    search_credits.clear()
    main._usage_cache.update(at=0.0, data=None)
    yield
    search_credits.clear()


def test_disabled_without_credentials():
    assert shared_cache.enabled() is False
    assert shared_cache.get("x") is None
    assert shared_cache.command("GET", "x") is None


def test_vercel_integration_variable_names_work(monkeypatch):
    monkeypatch.setenv("KV_REST_API_URL", "https://redis.example.com/")
    monkeypatch.setenv("KV_REST_API_TOKEN", "token")
    assert shared_cache.enabled() is True


def test_put_then_get_round_trips_json(redis):
    assert shared_cache.put("text:red shoes", {"best_matches": [1, 2]}, 3600, wait=True)
    assert ["SET", "vistora:text:red shoes", json.dumps({"best_matches": [1, 2]}), "EX", 3600] in redis.commands
    assert shared_cache.get("text:red shoes") == {"best_matches": [1, 2]}


def test_a_failing_redis_is_skipped_for_a_while(redis):
    redis.fail = True
    assert shared_cache.get("a") is None
    calls = len(redis.commands)

    assert shared_cache.get("b") is None  # skipped, no new call
    assert len(redis.commands) == calls


def test_results_are_shared_between_instances(redis):
    main.store_cached_search("text:red shoes", {"best_matches": [1]})
    main._search_cache.clear()  # a different server instance starts empty

    assert main.get_cached_search("text:red shoes") == {"best_matches": [1]}
    # ...and is then kept in this instance's memory without writing back.
    writes = [c for c in redis.commands if c[0] == "SET"]
    assert main.get_cached_search("text:red shoes") == {"best_matches": [1]}
    assert [c for c in redis.commands if c[0] == "SET"] == writes


def test_without_a_shared_cache_memory_still_works():
    main.store_cached_search("k", {"best_matches": [1]})
    assert main.get_cached_search("k") == {"best_matches": [1]}
    assert main.get_cached_search("missing") is None


def test_text_searches_are_counted(redis, monkeypatch):
    monkeypatch.setattr(
        main, "search_shopping_text", lambda query, n: {"best_matches": [{"name": "a"}], "cheapest_alternatives": []}
    )

    client.post("/api/v1/products/search-by-text", json={"query": "Red  Shoes"})
    client.post("/api/v1/products/search-by-text", json={"query": "red shoes"})

    assert redis.scores == {"red shoes": 2}


def test_warm_endpoint_needs_the_secret(monkeypatch):
    assert client.get("/api/v1/cron/warm").status_code == 404  # no secret configured

    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.get("/api/v1/cron/warm").status_code == 401
    assert client.get("/api/v1/cron/warm", headers={"Authorization": "Bearer wrong"}).status_code == 401


@pytest.fixture
def warm(redis, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setenv("SERPER_API_KEY", "k")
    monkeypatch.setattr(main, "WARM_LIMIT", 3)
    monkeypatch.setattr(main, "POPULAR_SEARCHES", ["seed one", "seed two", "seed three"])
    # The usage check the job makes first: plenty of Serper searches left.
    monkeypatch.setattr(
        main, "fetch_search_usage",
        lambda: {"searches_left": 100, "text": {"searches_left": 900}, "fast_photo": None},
    )
    searched = []

    def fake_search(query, limit):
        searched.append(query)
        return {"best_matches": [{"name": query}], "cheapest_alternatives": []}

    monkeypatch.setattr(main, "search_shopping_text", fake_search)
    return searched


def call_warm():
    return client.get("/api/v1/cron/warm", headers={"Authorization": "Bearer s3cret"})


def test_warm_searches_popular_queries_that_are_not_cached(redis, warm):
    redis.scores = {"blue jeans": 9, "red shoes": 5}
    # "red shoes" is already cached, so only the other two cost a search.
    main.store_cached_search(main.text_cache_key("red shoes"), {"best_matches": [1]})

    response = call_warm()

    assert response.status_code == 200
    assert response.json() == {"warmed": ["blue jeans", "seed one"], "already_cached": 1, "failed": 0}
    assert warm == ["blue jeans", "seed one"]
    # Warmed results live in the shared cache for the longer warm lifetime.
    assert any(
        c[0] == "SET" and c[1] == "vistora:text:blue jeans" and c[4] == main.WARM_TTL_SECONDS
        for c in redis.commands
    )


def test_warm_does_nothing_without_a_shared_cache(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setattr(main, "search_shopping_text", lambda *a: pytest.fail("must not search"))

    assert call_warm().json() == {"skipped": "no shared cache is configured"}


def test_warm_leaves_the_credits_alone_when_serper_is_low(redis, warm, monkeypatch):
    monkeypatch.setattr(
        main, "fetch_search_usage",
        lambda: {"searches_left": 100, "text": {"searches_left": 120}, "fast_photo": None},
    )

    body = call_warm().json()

    assert "keeping them for visitors" in body["skipped"] and warm == []


def test_warm_does_not_use_photo_credits_when_serper_is_not_set_up(redis, warm, monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY")

    assert "Serper" in call_warm().json()["skipped"] and warm == []


# --- the cache's health, shown on the status check ---------------------------------


class Answer:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


class OneAnswer:
    def __init__(self, answer=None, error=None):
        self.answer, self.error = answer, error

    def post(self, url, headers=None, json=None, timeout=None):
        if self.error:
            raise self.error
        return self.answer


def configured(monkeypatch, session):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://secret-host.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "secret-token")
    monkeypatch.setattr(shared_cache, "_session", session)


def test_health_is_none_when_the_cache_is_not_set_up():
    assert shared_cache.health() is None


def test_health_reports_a_working_cache(monkeypatch):
    configured(monkeypatch, OneAnswer(Answer(200, {"result": "PONG"})))
    health = shared_cache.health()
    assert health["ok"] is True and health["detail"] == "working" and isinstance(health["ms"], int)


def test_health_reports_a_rejected_token_without_leaking_it(monkeypatch):
    configured(monkeypatch, OneAnswer(Answer(401)))
    health = shared_cache.health()
    assert health["ok"] is False and "token was rejected" in health["detail"]
    assert "secret" not in json.dumps(health)


def test_health_reports_an_unreachable_cache_without_leaking_the_address(monkeypatch):
    configured(monkeypatch, OneAnswer(error=OSError("could not reach https://secret-host.upstash.io")))
    health = shared_cache.health()
    assert health["ok"] is False and "not reachable" in health["detail"]
    assert "secret" not in json.dumps(health)


def test_health_ignores_the_pause_after_an_earlier_failure(monkeypatch):
    configured(monkeypatch, OneAnswer(Answer(200, {"result": "PONG"})))
    monkeypatch.setattr(shared_cache, "_down_until", shared_cache.time.monotonic() + 999)
    assert shared_cache.health()["ok"] is True  # it asks again, so a fixed token shows up at once


def credits_ok(monkeypatch):
    monkeypatch.setattr(
        main, "fetch_search_usage",
        lambda: {"searches_left": 100, "searches_per_month": 250, "text": {"searches_left": 900}, "fast_photo": None},
    )


def test_status_is_ok_with_a_working_cache(monkeypatch):
    credits_ok(monkeypatch)
    configured(monkeypatch, OneAnswer(Answer(200, {"result": "PONG"})))

    response = client.get("/api/v1/usage/status")

    assert response.status_code == 200 and response.json()["shared_cache"]["ok"] is True


def test_status_is_503_when_the_cache_rejects_its_token(monkeypatch):
    credits_ok(monkeypatch)
    configured(monkeypatch, OneAnswer(Answer(401)))

    response = client.get("/api/v1/usage/status")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "low"
    assert body["problems"] == ["Shared cache (Upstash): the token was rejected (HTTP 401)"]
    assert "secret" not in response.text


def test_status_leaves_the_cache_out_when_it_is_not_set_up(monkeypatch):
    credits_ok(monkeypatch)

    response = client.get("/api/v1/usage/status")

    assert response.status_code == 200 and "shared_cache" not in response.json()
