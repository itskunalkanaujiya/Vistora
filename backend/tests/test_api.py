import json

import pytest
from fastapi.testclient import TestClient

import image_shopping_service as s
import main
from conftest import FakeResponse

SEARCH = "/api/v1/products/search-by-image"
STREAM = "/api/v1/products/search-by-image/stream"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def fake_search(monkeypatch):
    """Replace the online search; records how often it really runs."""
    calls = []

    def search(image_path, max_results, on_event=None, query=None):
        calls.append(query)
        if on_event:
            on_event("identified", {"online_search_query": "watch"})
            on_event("preview", {
                "best_matches": [{"name": "Watch", "price": None, "pending": True}],
                "cheapest_alternatives": [],
                "online_search_query": "watch",
            })
        return {
            "best_matches": [{"name": "Watch", "price": 999.0, "pending": False}],
            "cheapest_alternatives": [],
            "online_search_query": "watch",
        }

    monkeypatch.setattr(main, "search_online_products", search)
    return calls


def upload(client, path, data):
    return client.post(path, files={"file": ("photo.png", data, "image/png")})


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_rejects_empty_and_non_image_uploads(client):
    assert upload(client, SEARCH, b"").status_code == 400
    response = client.post(SEARCH, files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_repeat_search_is_served_from_cache(client, fake_search, png_bytes):
    first = upload(client, SEARCH, png_bytes("red")).json()
    second = upload(client, SEARCH, png_bytes("red")).json()
    other = upload(client, SEARCH, png_bytes("blue")).json()

    assert (first["cached"], second["cached"], other["cached"]) == (False, True, False)
    assert len(fake_search) == 2


def test_query_is_a_separate_cached_search(client, fake_search, png_bytes):
    photo = png_bytes("red")
    plain = client.post(SEARCH, files={"file": ("p.png", photo, "image/png")}).json()
    refined = client.post(
        SEARCH,
        files={"file": ("p.png", photo, "image/png")},
        data={"query": "  Casio   G-Shock  MTG-B3000 "},
    ).json()
    again = client.post(
        SEARCH,
        files={"file": ("p.png", photo, "image/png")},
        data={"query": "casio g-shock mtg-b3000"},
    ).json()

    assert (plain["cached"], refined["cached"], again["cached"]) == (False, False, True)
    # Extra spaces are removed before searching.
    assert fake_search == [None, "Casio G-Shock MTG-B3000"]


def test_clean_query():
    assert main.clean_query(None) is None
    assert main.clean_query("   ") is None
    assert main.clean_query("a  b\n c") == "a b c"
    assert len(main.clean_query("x" * 500)) == main.MAX_QUERY_LENGTH


def test_stream_sends_events_in_order(client, fake_search, png_bytes):
    with client.stream("POST", STREAM, files={"file": ("p.png", png_bytes("green"), "image/png")}) as r:
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.iter_lines() if line]

    assert [e["type"] for e in events] == ["stage", "identified", "preview", "final"]
    assert events[2]["best_matches"][0]["pending"] is True
    assert events[3]["best_matches"][0]["price"] == 999.0


def test_stream_reports_search_failures(client, monkeypatch, png_bytes):
    def failing(*args, **kwargs):
        raise RuntimeError("SerpApi down")

    monkeypatch.setattr(main, "search_online_products", failing)
    with client.stream("POST", STREAM, files={"file": ("p.png", png_bytes("teal"), "image/png")}) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]

    assert [e["type"] for e in events] == ["stage", "error"]


def test_search_limit(client, fake_search, png_bytes, monkeypatch):
    monkeypatch.setattr(main, "SEARCH_LIMIT", 2)

    assert upload(client, SEARCH, png_bytes("red")).status_code == 200
    assert upload(client, SEARCH, png_bytes("green")).status_code == 200

    blocked = upload(client, STREAM, png_bytes("blue"))
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # Cached results are free even when over the limit.
    assert upload(client, SEARCH, png_bytes("red")).json()["cached"] is True


def test_lens_retries_once_when_empty(monkeypatch, tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8 fake jpeg")
    monkeypatch.setenv("SERPAPI_API_KEY", "test")
    monkeypatch.setattr(s.requests, "post", lambda *a, **k: _Json({"image_id": "img"}))

    no_cache_flags = []
    matches = [
        {"title": "G Shock watch", "source": "finebuy", "link": "https://finebuy.co.in/product/a/"},
        {"title": "G Shock watch", "source": "finebuy", "link": "https://finebuy.co.in/product/b/"},
        {"title": "Other watch", "source": "Flipkart", "link": "https://www.flipkart.com/x/p/itm1"},
    ]

    def fake_get(url, params, timeout):
        no_cache_flags.append(params.get("no_cache"))
        assert "q" not in params  # no query: Lens identifies the product itself
        return _Json({"search_metadata": {}} if len(no_cache_flags) == 1 else {"visual_matches": matches})

    monkeypatch.setattr(s.requests, "get", fake_get)

    candidates = s.run_google_lens(image)
    assert no_cache_flags == [None, "true"]
    # The same listing under two URLs is kept once.
    assert [c["link"] for c in candidates] == [
        "https://finebuy.co.in/product/a/",
        "https://www.flipkart.com/x/p/itm1",
    ]


class _Json:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_lens_query_is_sent_as_q(monkeypatch, tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8 fake jpeg")
    monkeypatch.setenv("SERPAPI_API_KEY", "test")
    monkeypatch.setattr(s.requests, "post", lambda *a, **k: _Json({"image_id": "img"}))

    sent = []
    match = {"title": "Casio watch", "source": "Flipkart", "link": "https://www.flipkart.com/x/p/itm1"}

    def fake_get(url, params, timeout):
        sent.append(params.get("q"))
        return _Json({"visual_matches": [match]})

    monkeypatch.setattr(s.requests, "get", fake_get)
    s.run_google_lens(image, query="casio g-shock")
    assert sent == ["casio g-shock"]


def test_search_limit_is_per_visitor_behind_a_proxy(client, fake_search, png_bytes, monkeypatch):
    monkeypatch.setattr(main, "SEARCH_LIMIT", 1)
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", True)

    def search_as(visitor, color):
        return client.post(
            SEARCH,
            files={"file": ("p.png", png_bytes(color), "image/png")},
            headers={"X-Forwarded-For": f"{visitor}, 10.0.0.1"},
        )

    assert search_as("203.0.113.5", "red").status_code == 200
    assert search_as("198.51.100.7", "green").status_code == 200  # different visitor
    assert search_as("203.0.113.5", "blue").status_code == 429


def test_forwarded_header_ignored_unless_trusted(client, monkeypatch):
    monkeypatch.setattr(main, "TRUST_PROXY_HEADERS", False)
    request = type("R", (), {"headers": {"x-forwarded-for": "1.2.3.4"},
                             "client": type("C", (), {"host": "127.0.0.1"})()})()
    assert main.client_address(request) == "127.0.0.1"


def test_cors_allows_configured_origins(monkeypatch):
    import importlib

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://vistora-app.vercel.app/")
    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", r"https://vistora(-[a-z0-9-]+)?\.vercel\.app")
    try:
        app = importlib.reload(main).app
        test_client = TestClient(app)

        def allowed(origin):
            response = test_client.options(
                SEARCH,
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )
            return response.headers.get("access-control-allow-origin") == origin

        assert allowed("https://vistora-app.vercel.app")
        assert allowed("https://vistora-git-main-kunal.vercel.app")
        assert allowed("http://localhost:5173")
        assert not allowed("https://evil.example.com")
    finally:
        monkeypatch.delenv("ALLOWED_ORIGINS")
        monkeypatch.delenv("ALLOWED_ORIGIN_REGEX")
        importlib.reload(main)


def test_usage_reports_searches_left_and_is_cached(monkeypatch):
    calls = []

    def account(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(data={
            "total_searches_left": 167, "searches_per_month": 250,
            "this_month_usage": 83, "plan_renewal_date": "2026-11-09",
            "plan_name": "Free Plan", "api_key": "secret",
        })

    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(main.requests, "get", account)
    main._usage_cache.update(at=0.0, data=None)
    client = TestClient(main.app)

    first = client.get("/api/v1/usage").json()
    client.get("/api/v1/usage")

    assert first == {
        "searches_left": 167, "searches_per_month": 250, "used_this_month": 83,
        "renews_on": "2026-11-09", "plan": "Free Plan", "text": None, "fast_photo": None,
    }
    assert len(calls) == 1  # cached; the API key is never returned


def test_usage_unavailable_gives_503(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(main.requests, "get", broken)
    main._usage_cache.update(at=0.0, data=None)
    assert TestClient(main.app).get("/api/v1/usage").status_code == 503


def test_usage_includes_serper_credits(monkeypatch):
    def get(url, params=None, headers=None, timeout=None):
        if "serper" in url:
            return FakeResponse(data={"balance": 2484, "rateLimit": 5})
        return FakeResponse(data={"total_searches_left": 160, "searches_per_month": 250})

    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setenv("SERPER_API_KEY", "serper-key")
    monkeypatch.setattr(main.requests, "get", get)
    main._usage_cache.update(at=0.0, data=None)

    usage = TestClient(main.app).get("/api/v1/usage").json()
    assert usage["searches_left"] == 160
    assert usage["text"] == {"provider": "serper", "credits": 2484, "searches_left": 1242}


def test_usage_includes_searchapi_credits(monkeypatch):
    def get(url, params=None, headers=None, timeout=None):
        if "searchapi" in url:
            return FakeResponse(data={"account": {"remaining_credits": 96, "monthly_allowance": 0}})
        return FakeResponse(data={"total_searches_left": 158, "searches_per_month": 250})

    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setenv("SEARCHAPI_API_KEY", "k2")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "t")
    monkeypatch.setattr(main.requests, "get", get)
    main._usage_cache.update(at=0.0, data=None)
    usage = TestClient(main.app).get("/api/v1/usage").json()
    assert usage["fast_photo"] == {"provider": "searchapi", "searches_left": 96, "enabled": True}


def _fast_lens_env(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-key")
    monkeypatch.setenv("SEARCHAPI_API_KEY", "searchapi-key")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "blob-token")


def test_fast_lens_uses_searchapi_with_a_temporary_blob(monkeypatch, tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8 fake jpeg")
    _fast_lens_env(monkeypatch)
    calls = []

    def put(url, data, headers, timeout):
        calls.append(("upload", headers["x-content-type"]))
        return FakeResponse(data={"url": "https://x.public.blob.vercel-storage.com/lens/photo-abc.jpg"})

    def get(url, params, timeout):
        calls.append(("search", params["url"], params["country"]))
        return FakeResponse(data={"visual_matches": [{
            "title": "Casio watch", "source": "Flipkart", "link": "https://www.flipkart.com/x/p/itm1",
            "price": "₹2,995*", "extracted_price": 2995, "currency": "INR",
            "image": {"link": "https://img.example/full.jpg"}, "thumbnail": "https://img.example/t.jpg",
        }]})

    deleted = []
    monkeypatch.setattr(s.requests, "put", put)
    monkeypatch.setattr(s.requests, "get", get)
    monkeypatch.setattr(s, "delete_temporary_image", deleted.append)
    monkeypatch.setattr(s.requests, "post", lambda *a, **k: pytest.fail("SerpApi should not be used"))

    candidates = s.run_google_lens(image)

    assert calls[0] == ("upload", "image/jpeg")
    assert calls[1] == ("search", "https://x.public.blob.vercel-storage.com/lens/photo-abc.jpg", "in")
    assert candidates[0]["image"] == "https://img.example/full.jpg"
    assert s.extract_price(candidates[0])["price"] == 2995
    import time
    for _ in range(50):
        if deleted:
            break
        time.sleep(0.01)
    assert deleted == ["https://x.public.blob.vercel-storage.com/lens/photo-abc.jpg"]


def test_fast_lens_falls_back_to_serpapi(monkeypatch, tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8 fake jpeg")
    _fast_lens_env(monkeypatch)
    monkeypatch.setattr(s, "upload_temporary_image", lambda path, mime: "https://blob.example/p.jpg")
    monkeypatch.setattr(s, "delete_temporary_image", lambda url: None)
    monkeypatch.setattr(s.requests, "post", lambda *a, **k: _Json({"image_id": "img"}))
    match = {"title": "Casio watch", "source": "Flipkart", "link": "https://www.flipkart.com/x/p/itm1"}

    def get(url, params, timeout):
        if "searchapi" in url:
            return FakeResponse(data={"error": "You have run out of credits."}, status_code=429)
        return _Json({"visual_matches": [match]})

    monkeypatch.setattr(s.requests, "get", get)
    assert [c["title"] for c in s.run_google_lens(image)] == ["Casio watch"]
