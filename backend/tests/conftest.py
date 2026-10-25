import io
import sys
from pathlib import Path

import pytest
import requests
from PIL import Image

# Make the backend modules importable from the tests folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fast_photo  # noqa: E402
import image_shopping_service  # noqa: E402
import llm_query_parser  # noqa: E402
import main  # noqa: E402
import outfit_service  # noqa: E402
import text_shopping_service  # noqa: E402


@pytest.fixture(autouse=True)
def reset_server_state():
    """Each test starts with an empty cache and no recorded searches."""
    main._search_cache.clear()
    main._search_log.clear()
    main._tryon_log.clear()
    main._overlay_log.clear()
    main._overlay_cache.clear()
    main._assistant_log.clear()
    main._style_log.clear()
    main._watch_log.clear()
    outfit_service._skip_until.clear()
    yield
    main._search_cache.clear()
    main._search_log.clear()
    main._tryon_log.clear()
    main._overlay_log.clear()
    main._overlay_cache.clear()


class _RequestsShim:
    """Stands in for a requests.Session in tests: calls whatever requests.get,
    .post or .put is at call time, so tests can keep mocking those."""

    def get(self, *args, **kwargs):
        return requests.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return requests.post(*args, **kwargs)

    def put(self, *args, **kwargs):
        return requests.put(*args, **kwargs)


@pytest.fixture(autouse=True)
def mockable_http_sessions(monkeypatch):
    """The services reuse connections through module-level sessions; tests
    mock requests.* instead, so route the sessions through it."""
    shim = _RequestsShim()
    monkeypatch.setattr(image_shopping_service, "_api_session", shim)
    monkeypatch.setattr(llm_query_parser, "_session", shim)
    monkeypatch.setattr(text_shopping_service, "_session", shim)


@pytest.fixture(autouse=True)
def fast_photo_on_in_tests(monkeypatch):
    """The fast provider is off by default in the app; tests of it turn it on (tests of the switch undo this)."""
    monkeypatch.setenv("FAST_PHOTO", "on")
    fast_photo.reset()
    yield
    fast_photo.reset()


@pytest.fixture(autouse=True)
def no_serper(monkeypatch):
    """Tests never call Serper, SearchApi or Vercel Blob; tests that need
    them set fake keys."""
    for name in (
        "SERPER_API_KEY", "SEARCHAPI_API_KEY", "BLOB_READ_WRITE_TOKEN", "GROQ_API_KEY", "GEMINI_API_KEY",
        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_URL", "KV_REST_API_TOKEN", "CRON_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def png_bytes():
    """Return PNG bytes for a solid-colour image."""

    def make(color="red", size=(120, 120)):
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, format="PNG")
        return buffer.getvalue()

    return make


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, text="", data=None, status_code=200):
        self.text = text
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._data
