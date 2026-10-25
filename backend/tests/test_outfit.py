import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
import outfit_service as o
from conftest import FakeResponse

OUTFIT = {
    "gender": "men",
    "items": [
        {"type": "t-shirt", "description": "yellow blue striped t-shirt", "box": [375, 0, 680, 245]},
        {"type": "jeans", "description": "dark blue slim fit denim jeans", "box": [435, 225, 635, 640]},
        {"type": "watch", "description": "silver metal band wristwatch", "box": [615, 165, 616, 200]},
        {"type": "", "description": "nothing"},
    ],
}


def vision_reply(data, status=200):
    return FakeResponse(data={"choices": [{"message": {"content": json.dumps(data)}}]}, status_code=status)


@pytest.fixture(autouse=True)
def no_clip(monkeypatch):
    """Tests never load CLIP or download listing photos."""
    monkeypatch.setattr(o, "load_clip_model", lambda: (None, None))
    monkeypatch.setattr(o, "download_thumbnails", lambda candidates, deadline=None: [None] * len(candidates))
    monkeypatch.setattr(o, "compute_visual_similarity_scores", lambda image, candidates, thumbnails=None: {})


@pytest.fixture
def vision(monkeypatch):
    sent = []

    def post(url, headers, json, timeout):
        sent.append(json)
        return vision_reply(OUTFIT)

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(o.requests, "post", post)
    return sent


def test_identify_outfit_reads_items_and_boxes(vision):
    outfit = o.identify_outfit(Image.new("RGB", (1200, 1200), "white"))

    image_part = vision[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_part.startswith("data:image/jpeg;base64,")
    assert "[x1, y1, x2, y2]" in vision[0]["messages"][0]["content"][0]["text"]
    assert outfit["gender"] == "men" and outfit["model"] == "Groq"
    assert [item["type"] for item in outfit["items"]] == ["t-shirt", "jeans", "watch"]
    assert outfit["items"][0]["box"] == [0.375, 0.0, 0.68, 0.245]
    assert outfit["items"][2]["box"] is None  # too thin to be a real box


def test_find_outfit_searches_each_item_with_gender(vision, monkeypatch):
    searched = []

    def search(query, max_results, understand, min_relevance=None):
        searched.append((query, understand))
        return {"best_matches": [{"name": f"{query} listing"}], "cheapest_alternatives": []}

    monkeypatch.setattr(o, "search_products_by_text", search)
    events = []
    outfit = o.find_outfit(Image.new("RGB", (600, 800)), on_event=lambda kind, data: events.append(kind))

    assert sorted(searched) == sorted([
        ("men yellow blue striped t-shirt", False),
        ("men dark blue slim fit denim jeans", False),
        ("men silver metal band wristwatch", False),
    ])
    assert events == ["items", "item", "item", "item"]
    assert all(item["best_matches"] for item in outfit["items"])


def test_busy_model_gives_a_clear_message(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(o.requests, "post", lambda *a, **k: FakeResponse(data={}, status_code=429))
    with pytest.raises(o.OutfitError, match="busy"):
        o.identify_outfit(Image.new("RGB", (100, 100)))


def test_no_person_found(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(o.requests, "post", lambda *a, **k: vision_reply({"gender": "unisex", "items": []}))
    with pytest.raises(o.OutfitError, match="Couldn't find"):
        o.find_outfit(Image.new("RGB", (100, 100)))


def test_outfit_endpoint_streams_items_then_final(vision, monkeypatch, png_bytes):
    monkeypatch.setattr(o, "search_products_by_text", lambda q, n, understand, min_relevance=None: {
        "best_matches": [{"name": q}], "cheapest_alternatives": []})
    client = TestClient(main.app)

    def stream():
        response = client.post("/api/v1/outfit/stream", files={"file": ("me.png", png_bytes("blue"), "image/png")})
        return [json.loads(line) for line in response.text.splitlines() if line]

    events = stream()
    assert [e["type"] for e in events] == ["stage", "items", "item", "item", "item", "final"]
    assert len(events[-1]["items"]) == 3

    again = stream()  # the same photo is served from the cache
    assert [e["type"] for e in again] == ["final"] and again[0]["cached"] is True


def test_outfit_endpoint_reports_model_errors(monkeypatch, png_bytes):
    events = TestClient(main.app).post(
        "/api/v1/outfit/stream", files={"file": ("me.png", png_bytes("red"), "image/png")}
    ).text.splitlines()
    error = json.loads(events[-1])
    assert error["type"] == "error" and "isn't set up" in error["detail"]  # no GROQ_API_KEY in tests


def test_portrait_photos_are_padded_to_a_square():
    square, frame = o.square_photo(Image.new("RGB", (600, 1200), "white"))

    assert square.size == (512, 512) or square.size[0] == square.size[1]
    left, top, width, height, side = frame
    assert (top, side) == (0, height) and left == (side - width) // 2
    # The middle half of the square is the whole photo's width.
    assert o._box([250, 0, 750, 500], frame) == [0.0, 0.0, 1.0, 0.5]
    # Gemini's [ymin, xmin, ymax, xmax] order.
    assert o._box([0, 250, 500, 750], frame, "yxyx") == [0.0, 0.0, 1.0, 0.5]
    assert o._box([400, 400, 405, 405], frame) is None  # too small


def test_gemini_is_tried_first_then_groq(monkeypatch):
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, json["model"]))
        if "googleapis" in url:
            return FakeResponse(data={}, status_code=429)
        return vision_reply(OUTFIT)

    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(o.requests, "post", post)

    outfit = o.identify_outfit(Image.new("RGB", (800, 800)))

    assert calls[0] == (o.GEMINI_URL, o.GEMINI_MODELS[0])
    assert calls[-1][0] == o.GROQ_URL
    assert outfit["model"] == "Groq" and len(outfit["items"]) == 3


def test_gemini_boxes_are_read_y_first(monkeypatch):
    sent = []

    def post(url, headers, json, timeout):
        sent.append(json)
        return vision_reply({"gender": "women", "items": [
            {"type": "sunglasses", "description": "black cat eye sunglasses", "box_2d": [100, 300, 200, 600]},
        ]})

    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(o.requests, "post", post)

    outfit = o.identify_outfit(Image.new("RGB", (1000, 1000)))

    assert "[ymin, xmin, ymax, xmax]" in sent[0]["messages"][0]["content"][0]["text"]
    assert outfit["model"] == "Gemini"
    assert outfit["items"][0]["box"] == [0.3, 0.1, 0.6, 0.2]


def test_retired_gemini_model_is_skipped(monkeypatch):
    models = []

    def post(url, headers, json, timeout):
        models.append(json["model"])
        if len(models) == 1:
            return FakeResponse(data={}, status_code=404)
        return vision_reply(OUTFIT)

    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(o.requests, "post", post)

    assert o.identify_outfit(Image.new("RGB", (500, 500)))["model"] == "Gemini"
    assert models == o.GEMINI_MODELS[:2]


def listing(name, price, score):
    return {"name": name, "price": price, "product_url": f"https://shop/{name}", "image_url": f"https://img/{name}", "_score": score}


def test_listings_are_ranked_by_how_alike_they_look(monkeypatch):
    listings = [
        listing("plain", 400, 0.60),
        listing("printed", 900, 0.80),
        listing("similar", 300, 0.77),
        listing("close", 700, 0.75),
        listing("designer", 90000, 0.79),
        listing("okay", 500, 0.73),
    ]
    monkeypatch.setattr(
        o, "compute_visual_similarity_scores",
        lambda crop, candidates, thumbnails=None: {i: p["_score"] for i, p in enumerate(candidates)},
    )

    best, cheapest = o.rank_by_look(Image.new("RGB", (50, 50)), {
        "best_matches": listings[:3], "cheapest_alternatives": listings[3:],
    })

    # "designer" is priced far above the rest; "plain" looks too different.
    assert [p["name"] for p in best] == ["printed", "similar", "close", "okay"]
    assert cheapest == []
    assert all("visual_similarity_score" not in p for p in best)


def test_without_a_crop_the_search_order_is_kept():
    result = {"best_matches": [listing("a", 1, 0)], "cheapest_alternatives": [listing("b", 1, 0)]}
    best, cheapest = o.rank_by_look(None, result)
    assert [p["name"] for p in best + cheapest] == ["a", "b"]


def test_crop_item_adds_a_margin_and_skips_tiny_boxes():
    image = Image.new("RGB", (1000, 1000))
    assert o.crop_item(image, [0.2, 0.2, 0.4, 0.6]).size == (232, 464)
    assert o.crop_item(image, [0.5, 0.5, 0.51, 0.51]) is None
    assert o.crop_item(image, None) is None


def test_outfit_items_search_a_wide_pool_when_they_have_a_crop(vision, monkeypatch):
    calls = []

    def search(query, max_results, understand, min_relevance=None):
        calls.append((max_results, min_relevance))
        return {"best_matches": [], "cheapest_alternatives": []}

    monkeypatch.setattr(o, "search_products_by_text", search)
    monkeypatch.setattr(o, "visual_ranking_available", lambda: True)
    o.find_outfit(Image.new("RGB", (1000, 1000)))

    # t-shirt and jeans have boxes; the watch's box was too thin.
    assert sorted(calls, key=str) == sorted(
        [(o.SEARCH_POOL, o.LOOSE_RELEVANCE)] * 2 + [(o.RESULTS_PER_ITEM, None)], key=str
    )


def test_without_clip_a_crop_item_uses_the_normal_strict_search(vision, monkeypatch):
    calls = []

    def search(query, max_results, understand, min_relevance=None):
        calls.append((max_results, min_relevance))
        return {"best_matches": [], "cheapest_alternatives": []}

    monkeypatch.setattr(o, "search_products_by_text", search)
    monkeypatch.setattr(o, "visual_ranking_available", lambda: False)
    o.find_outfit(Image.new("RGB", (1000, 1000)))

    assert calls and all(call == (o.RESULTS_PER_ITEM, None) for call in calls)
