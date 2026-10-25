import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import image_shopping_service as s
import main
import search_credits as credits
import text_shopping_service as t

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_credits():
    credits.clear()
    main._usage_cache.update(at=0.0, data=None)
    yield
    credits.clear()
    main._usage_cache.update(at=0.0, data=None)


# --- remembering what is empty ---------------------------------------------


def test_a_provider_is_only_empty_after_it_was_read_as_empty():
    assert not credits.known_empty("serpapi")  # never read: try it
    credits.record("serpapi", 12)
    assert not credits.known_empty("serpapi")
    credits.record("serpapi", 0)
    assert credits.known_empty("serpapi")
    credits.record("serpapi", None)  # unknown again
    assert not credits.known_empty("serpapi")


def test_an_old_empty_reading_is_not_trusted(monkeypatch):
    credits.record("serper", 0)
    now = credits.time.monotonic()
    monkeypatch.setattr(credits.time, "monotonic", lambda: now + credits.TRUST_SECONDS + 1)
    assert not credits.known_empty("serper")  # credits may have been topped up since


# --- photo search ------------------------------------------------------------


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (60, 60), "red").save(path)
    return path


MATCHES = [{"title": "Red watch", "link": "https://www.flipkart.com/red-watch/p/1"}]


@pytest.fixture
def lens(monkeypatch):
    calls = []
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setattr(s, "fast_lens_available", lambda: True)
    monkeypatch.setattr(s, "run_searchapi_lens", lambda *a, **k: calls.append("searchapi") or MATCHES)
    monkeypatch.setattr(s, "run_serpapi_lens", lambda *a, **k: calls.append("serpapi") or MATCHES)
    return calls


def test_photo_search_uses_the_fast_provider_first(lens, photo):
    s.run_google_lens(photo)
    assert lens == ["searchapi"]


def test_photo_search_skips_a_fast_provider_that_is_out_of_credits(lens, photo):
    credits.record("searchapi", 0)
    s.run_google_lens(photo)
    assert lens == ["serpapi"]


def test_photo_search_says_so_when_every_provider_is_empty(lens, photo):
    credits.record("searchapi", 0)
    credits.record("serpapi", 0)
    with pytest.raises(credits.SearchLimitError) as error:
        s.run_google_lens(photo)
    assert lens == []  # nothing was spent or waited for
    assert error.value.user_facing and "limit" in str(error.value)


def test_an_empty_backup_is_still_tried_if_the_fast_provider_failed(lens, photo, monkeypatch):
    credits.record("serpapi", 0)

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(s, "run_searchapi_lens", broken)
    s.run_google_lens(photo)  # the reading may be stale: try it rather than give up
    assert lens == ["serpapi"]


# --- text search ---------------------------------------------------------------


@pytest.fixture
def shopping(monkeypatch):
    calls = []
    monkeypatch.setenv("SERPER_API_KEY", "k")
    monkeypatch.setattr(t, "run_serper_shopping", lambda q: calls.append("serper") or [{"title": "a"}])
    monkeypatch.setattr(t, "run_google_shopping", lambda q: calls.append("serpapi") or [{"title": "b"}])
    return calls


def test_text_search_skips_serper_when_it_is_empty(shopping):
    credits.record("serper", 0)
    results, provider = t.fetch_shopping_results("shoes")
    assert provider == "serpapi" and shopping == ["serpapi"]


def test_text_search_says_so_when_every_provider_is_empty(shopping):
    credits.record("serper", 0)
    credits.record("serpapi", 0)
    with pytest.raises(credits.SearchLimitError):
        t.fetch_shopping_results("shoes")
    assert shopping == []


# --- the usage endpoint feeds the readings --------------------------------------


def test_reading_the_accounts_records_what_is_left(monkeypatch):
    class Account:
        def raise_for_status(self):
            pass

        def json(self):
            return {"total_searches_left": 0, "searches_per_month": 250}

    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Account())
    monkeypatch.setattr(main, "fetch_serper_usage", lambda: {"searches_left": 700})
    monkeypatch.setattr(main, "fetch_searchapi_usage", lambda: {"searches_left": 0})

    main.fetch_search_usage()

    assert credits.known_empty("serpapi") and credits.known_empty("searchapi")
    assert not credits.known_empty("serper")


# --- the status check an uptime monitor watches -----------------------------------


def usage(serpapi=100, searchapi=40, serper=500):
    return {
        "searches_left": serpapi,
        "searches_per_month": 250,
        "renews_on": "2026-11-09",
        "fast_photo": {"searches_left": searchapi} if searchapi is not None else None,
        "text": {"searches_left": serper} if serper is not None else None,
    }


def status_for(monkeypatch, data):
    monkeypatch.setattr(main, "fetch_search_usage", lambda: data)
    return client.get("/api/v1/usage/status")


def test_status_is_200_while_there_is_plenty(monkeypatch):
    response = status_for(monkeypatch, usage())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["problems"] == []
    assert body["providers"]["searchapi"] == {"label": "Fast photo searches (SearchApi)", "left": 40, "status": "ok"}


def test_status_is_503_when_a_provider_runs_low(monkeypatch):
    response = status_for(monkeypatch, usage(searchapi=9))
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "low"
    assert body["problems"] == ["Fast photo searches (SearchApi): only 9 left"]


def test_serpapi_counts_as_low_under_ten_percent_of_its_plan(monkeypatch):
    # 24 of 250 is under 10%, and also under the fixed threshold of 25.
    assert status_for(monkeypatch, usage(serpapi=24)).json()["status"] == "low"
    # 26 left is above both.
    main._usage_cache.update(at=0.0, data=None)
    assert status_for(monkeypatch, usage(serpapi=26)).status_code == 200


def test_status_reports_empty_as_the_worst_state(monkeypatch):
    main._usage_cache.update(at=0.0, data=None)
    response = status_for(monkeypatch, usage(serpapi=0, searchapi=3))
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "empty"
    assert "Photo and text searches (SerpApi): none left" in body["problems"]


def test_status_ignores_providers_that_are_not_set_up(monkeypatch):
    body = status_for(monkeypatch, usage(searchapi=None, serper=None)).json()
    assert body["status"] == "ok" and list(body["providers"]) == ["serpapi"]


# --- what a visitor sees when searches are paused -------------------------------------


def test_a_text_search_gets_a_clear_message_when_credits_are_gone(monkeypatch):
    def limit(query, count):
        raise credits.SearchLimitError()

    monkeypatch.setattr(main, "search_shopping_text", limit)
    response = client.post("/api/v1/products/search-by-text", json={"query": "red shoes"})

    assert response.status_code == 503
    assert "limit" in response.json()["detail"] and response.headers["retry-after"] == "3600"


def test_other_failures_keep_the_usual_error(monkeypatch):
    def broken(query, count):
        raise RuntimeError("provider down")

    monkeypatch.setattr(main, "search_shopping_text", broken)
    response = client.post("/api/v1/products/search-by-text", json={"query": "red shoes"})

    assert response.status_code == 502 and response.json()["detail"] == main.ONLINE_SEARCH_ERROR


def test_a_streamed_search_sends_the_message_as_its_error_event(monkeypatch):
    def limit(query, count):
        raise credits.SearchLimitError()

    monkeypatch.setattr(main, "search_shopping_text", limit)
    response = client.post("/api/v1/products/search-by-text/stream", json={"query": "red shoes"})
    events = [json.loads(line) for line in response.text.splitlines() if line]

    assert events[-1]["type"] == "error" and "limit" in events[-1]["detail"]
