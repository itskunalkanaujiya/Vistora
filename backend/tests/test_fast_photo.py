import pytest
from fastapi.testclient import TestClient

import fast_photo
import image_shopping_service as s
import main
import shared_cache
from test_shared_cache import FakeRedis, _SameThread

client = TestClient(main.app)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("SEARCHAPI_API_KEY", "k")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "t")


@pytest.fixture
def default_off(monkeypatch):
    monkeypatch.delenv("FAST_PHOTO", raising=False)
    fast_photo.reset()


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://redis.example.com")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "token")
    monkeypatch.setattr(shared_cache, "_session", fake)
    monkeypatch.setattr(shared_cache, "_down_until", 0.0)
    monkeypatch.setattr(shared_cache, "_writes", _SameThread())
    return fake


def test_the_fast_provider_is_off_by_default(keys, default_off):
    assert fast_photo.enabled() is False
    assert s.fast_lens_available() is False  # even with its keys set


def test_the_environment_can_keep_it_on(keys, default_off, monkeypatch):
    monkeypatch.setenv("FAST_PHOTO", "on")
    assert s.fast_lens_available() is True


def test_it_still_needs_its_keys(default_off, monkeypatch):
    fast_photo.turn_on(2)
    assert s.fast_lens_available() is False  # on, but SearchApi is not set up


def test_turning_it_on_lasts_only_for_the_hours_given(keys, default_off, monkeypatch):
    fast_photo.turn_on(2)
    assert s.fast_lens_available() is True

    now = fast_photo.time.time()
    monkeypatch.setattr(fast_photo.time, "time", lambda: now + 2 * 3600 + 1)
    assert s.fast_lens_available() is False  # back off by itself


def test_the_hours_are_kept_within_limits(default_off):
    assert fast_photo.turn_on(500)["until"] is not None
    now = fast_photo.time.time()
    assert fast_photo._override["until"] - now <= fast_photo.MAX_HOURS * 3600 + 5
    fast_photo.turn_on(0)
    assert fast_photo._override["until"] - fast_photo.time.time() >= 3600 - 5  # at least an hour


def test_turning_it_off_beats_the_environment(keys, monkeypatch):
    monkeypatch.setenv("FAST_PHOTO", "on")
    fast_photo.turn_off()
    assert fast_photo.enabled() is False


def test_every_server_follows_the_shared_switch(keys, default_off, redis):
    fast_photo.turn_on(3)
    assert "settings:fast_photo" in "".join(c[1].replace("vistora:", "") for c in redis.commands if c[0] == "SET")

    fast_photo.reset()  # a different server that has not heard of it yet
    assert fast_photo.enabled() is True  # reads it from the shared cache

    fast_photo.turn_off()
    fast_photo.reset()
    assert fast_photo.enabled() is False


def test_a_missing_shared_setting_means_off(keys, default_off, redis):
    assert fast_photo.enabled() is False


def test_photo_search_uses_the_backup_provider_while_it_is_off(keys, default_off, monkeypatch, tmp_path):
    from PIL import Image

    calls = []
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    matches = [{"title": "Red watch", "link": "https://www.flipkart.com/w/p/1"}]
    monkeypatch.setattr(s, "run_searchapi_lens", lambda *a, **k: calls.append("searchapi") or matches)
    monkeypatch.setattr(s, "run_serpapi_lens", lambda *a, **k: calls.append("serpapi") or matches)
    photo = tmp_path / "p.png"
    Image.new("RGB", (60, 60), "red").save(photo)

    s.run_google_lens(photo)
    assert calls == ["serpapi"]

    calls.clear()
    fast_photo.turn_on(1)
    s.run_google_lens(photo)
    assert calls == ["searchapi"]


# --- the admin address -------------------------------------------------------------


def test_the_admin_address_does_not_exist_without_a_secret(default_off):
    assert client.get("/api/v1/admin/fast-photo").status_code == 404
    assert client.post("/api/v1/admin/fast-photo", json={"on": True}).status_code == 404


def test_the_admin_address_needs_the_secret(default_off, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.get("/api/v1/admin/fast-photo").status_code == 401
    assert client.post("/api/v1/admin/fast-photo", json={"on": True}, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert fast_photo.enabled() is False


def test_the_admin_address_switches_it_on_and_off(keys, default_off, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    headers = {"Authorization": "Bearer s3cret"}

    assert client.get("/api/v1/admin/fast-photo", headers=headers).json()["on"] is False

    on = client.post("/api/v1/admin/fast-photo", json={"on": True, "hours": 3}, headers=headers).json()
    assert on["on"] is True and on["source"] == "admin switch" and on["until"].endswith("UTC")
    assert s.fast_lens_available() is True

    off = client.post("/api/v1/admin/fast-photo", json={"on": False}, headers=headers).json()
    assert off["on"] is False and s.fast_lens_available() is False


def test_the_usage_numbers_and_status_show_the_switch(keys, default_off, monkeypatch):
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: {"account": {"remaining_credits": 24}},
    })())
    assert main.fetch_searchapi_usage() == {"provider": "searchapi", "searches_left": 24, "enabled": False}

    fast_photo.turn_on(1)
    assert main.fetch_searchapi_usage()["enabled"] is True
