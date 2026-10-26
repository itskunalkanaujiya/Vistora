import pytest
from fastapi.testclient import TestClient
from PIL import Image
import io

import main
import pick_service
from outfit_service import OutfitError

client = TestClient(main.app)


def photo_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), (200, 200, 200)).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clear_limit():
    main._pick_log.clear()
    yield
    main._pick_log.clear()


def answer(items):
    return ({"items": items}, (0, 0, 80, 80, 80), "xyxy", "TestModel")


def test_items_get_thing_ids_and_items_without_a_box_are_dropped(monkeypatch):
    monkeypatch.setattr(
        pick_service, "ask_vision",
        lambda image, prompt, *a, **k: answer([
            {"type": "lamp", "description": "black desk lamp", "box": [100, 100, 500, 500]},
            {"type": "mug", "description": "white mug", "box": None},
        ]),
    )

    result = pick_service.identify_pickable(Image.new("RGB", (80, 80)))

    assert [i["id"] for i in result["items"]] == ["thing-1"]
    assert result["model"] == "TestModel"


def test_a_photo_with_nothing_to_buy_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(pick_service, "ask_vision", lambda *a, **k: answer([]))

    with pytest.raises(OutfitError):
        pick_service.identify_pickable(Image.new("RGB", (80, 80)))


def test_endpoint_returns_items_and_maps_errors(monkeypatch):
    monkeypatch.setattr(main, "identify_pickable", lambda image: {"items": [{"id": "thing-1"}], "model": "m"})
    ok = client.post("/api/v1/photo/items", files={"file": ("p.jpg", photo_bytes(), "image/jpeg")})
    assert ok.status_code == 200 and ok.json()["items"][0]["id"] == "thing-1"

    def nothing(image):
        raise OutfitError("Couldn't find anything")

    monkeypatch.setattr(main, "identify_pickable", nothing)
    empty = client.post("/api/v1/photo/items", files={"file": ("p.jpg", photo_bytes(), "image/jpeg")})
    assert empty.status_code == 422 and "anything" in empty.json()["detail"]


def test_endpoint_is_rate_limited(monkeypatch):
    monkeypatch.setattr(main, "identify_pickable", lambda image: {"items": [], "model": "m"})
    monkeypatch.setattr(main, "PICK_LIMIT", 1)
    send = lambda: client.post("/api/v1/photo/items", files={"file": ("p.jpg", photo_bytes(), "image/jpeg")}).status_code

    assert [send(), send()] == [200, 429]
