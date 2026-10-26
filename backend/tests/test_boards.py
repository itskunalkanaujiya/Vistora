import pytest
from fastapi.testclient import TestClient

import main
import shared_cache
from test_shared_cache import FakeResponse, redis  # noqa: F401  (the fake Upstash fixture)

client = TestClient(main.app)

ITEMS = [
    {"name": "Blue kurta", "price": 1499, "store": "Myntra", "image_url": "https://img.test/a.jpg", "url": "https://myntra.test/a"},
    {"name": "Green kurta", "price": 1299.5, "store": "Ajio", "image_url": "https://img.test/b.jpg", "url": "https://ajio.test/b"},
]


@pytest.fixture(autouse=True)
def clear_limits():
    main._board_log.clear()
    main._vote_log.clear()
    yield


@pytest.fixture
def hashes(redis, monkeypatch):  # noqa: F811
    """The fake Redis, taught HSET (votes) for these tests."""
    original = redis.post

    def post(url, headers=None, json=None, timeout=None):
        name, *args = json
        if name == "HSET":
            redis.hashes.setdefault(args[0], {})[args[1]] = args[2]
            return FakeResponse({"result": 1})
        return original(url, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(redis, "post", post)
    return redis


def test_a_board_is_created_read_and_voted_on(hashes):
    created = client.post("/api/v1/boards", json={"title": "Which kurta?", "items": ITEMS})
    assert created.status_code == 200
    board_id = created.json()["id"]

    board = client.get(f"/api/v1/boards/{board_id}").json()
    assert board["title"] == "Which kurta?" and board["votes"] == [0, 0] and board["my_vote"] is None

    mine = client.post(f"/api/v1/boards/{board_id}/vote", json={"voter": "voter-aaaa1111", "option": 1}).json()
    assert mine["votes"] == [0, 1] and mine["my_vote"] == 1

    client.post(f"/api/v1/boards/{board_id}/vote", json={"voter": "voter-bbbb2222", "option": 1})
    changed = client.post(f"/api/v1/boards/{board_id}/vote", json={"voter": "voter-aaaa1111", "option": 0}).json()
    assert changed["votes"] == [1, 1] and changed["total_votes"] == 2 and changed["my_vote"] == 0

    other = client.get(f"/api/v1/boards/{board_id}", params={"voter": "voter-cccc3333"}).json()
    assert other["my_vote"] is None
    assert "voters" not in other  # who voted for what is never sent out


def test_bad_boards_and_votes_are_refused(hashes):
    assert client.post("/api/v1/boards", json={"items": ITEMS[:1]}).status_code == 400
    assert client.post("/api/v1/boards", json={"items": ITEMS * 3}).status_code == 400
    board_id = client.post("/api/v1/boards", json={"items": ITEMS}).json()["id"]

    assert client.post(f"/api/v1/boards/{board_id}/vote", json={"voter": "x", "option": 0}).status_code == 400
    assert client.post(f"/api/v1/boards/{board_id}/vote", json={"voter": "voter-aaaa1111", "option": 5}).status_code == 400
    assert client.get("/api/v1/boards/nope-not-a-board").status_code == 404


def test_links_must_be_web_links_and_text_is_trimmed(hashes):
    items = [
        {**ITEMS[0], "url": "javascript:alert(1)", "image_url": "data:image/png;base64,AAAA", "name": "  A   very   long " + "x" * 300},
        ITEMS[1],
    ]
    board_id = client.post("/api/v1/boards", json={"items": items}).json()["id"]
    first = client.get(f"/api/v1/boards/{board_id}").json()["items"][0]

    assert first["url"] is None and first["image_url"] is None and len(first["name"]) == 140


def test_without_a_shared_cache_sharing_says_so(monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("KV_REST_API_URL", raising=False)

    response = client.post("/api/v1/boards", json={"items": ITEMS})

    assert response.status_code == 503 and "isn't set up" in response.json()["detail"]
    assert shared_cache.enabled() is False


def test_creating_boards_is_rate_limited(hashes, monkeypatch):
    monkeypatch.setattr(main, "BOARD_LIMIT", 2)
    codes = [client.post("/api/v1/boards", json={"items": ITEMS}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
