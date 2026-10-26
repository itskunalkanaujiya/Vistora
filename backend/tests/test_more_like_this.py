import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import image_shopping_service as s
import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_limit():
    main._like_log.clear()
    yield
    main._like_log.clear()


def test_internal_addresses_are_never_fetched(monkeypatch):
    fetched = []
    monkeypatch.setattr(s, "download_thumbnail", lambda url, follow_redirects=True: fetched.append(url))
    monkeypatch.setattr(s, "load_clip_model", lambda: (object(), object()))

    assert s.similarity_to_reference("http://127.0.0.1/a.jpg", ["http://169.254.169.254/x"]) == {}
    assert s.similarity_to_reference("file:///etc/passwd", []) == {}
    assert fetched == []


def test_scores_each_photo_against_the_reference_without_following_redirects(monkeypatch):
    seen = []
    monkeypatch.setattr(s, "public_image_url", lambda url: True)
    monkeypatch.setattr(s, "load_clip_model", lambda: (object(), object()))

    def fake_download(url, follow_redirects=True):
        seen.append((url, follow_redirects))
        return None if url.endswith("broken.jpg") else Image.new("RGB", (4, 4))

    monkeypatch.setattr(s, "download_thumbnail", fake_download)
    # reference first, then same / opposite
    monkeypatch.setattr(s, "encode_images", lambda m, p, images: np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))

    scores = s.similarity_to_reference(
        "https://img.test/ref.jpg", ["https://img.test/same.jpg", "https://img.test/broken.jpg", "https://img.test/other.jpg"]
    )

    assert scores == {"https://img.test/same.jpg": 1.0, "https://img.test/other.jpg": 0.0}
    assert all(follow is False for _, follow in seen)


def test_endpoint_returns_scores_and_validates_the_request(monkeypatch):
    monkeypatch.setattr(main, "similarity_to_reference", lambda ref, urls: {u: 0.5 for u in urls})

    ok = client.post("/api/v1/products/similar", json={"reference": "https://i.test/r.jpg", "images": ["https://i.test/a.jpg"]})
    assert ok.status_code == 200 and ok.json() == {"scores": {"https://i.test/a.jpg": 0.5}}

    assert client.post("/api/v1/products/similar", json={"reference": "x", "images": []}).status_code == 400
    too_many = ["https://i.test/%d.jpg" % i for i in range(41)]
    assert client.post("/api/v1/products/similar", json={"reference": "x", "images": too_many}).status_code == 400


def test_endpoint_is_rate_limited(monkeypatch):
    monkeypatch.setattr(main, "similarity_to_reference", lambda ref, urls: {})
    monkeypatch.setattr(main, "LIKE_LIMIT", 2)
    body = {"reference": "https://i.test/r.jpg", "images": ["https://i.test/a.jpg"]}

    codes = [client.post("/api/v1/products/similar", json=body).status_code for _ in range(3)]

    assert codes == [200, 200, 429]
