import pytest

import image_shopping_service as s


def test_title_keywords_keep_brand_names():
    words = s.title_keywords({"title": "Men's G Shock Watch, G-SHOCK GA-2100 a Watch"})
    assert words == ["men", "g-shock", "watch", "g-shock", "ga-2100", "watch"]


def test_derive_product_query_finds_consensus():
    titles = [
        "Nike Air Zoom Pegasus 41 Men's Road Running Shoes - Black",
        "Buy Nike Pegasus 41 Running Shoes for Men Online at Best Price",
        "NIKE Air Zoom Pegasus 41 Running Shoes For Men (Black)",
        "Pegasus 41 Black White Men's Running Shoe",
        "Nike Pegasus 41 review",
    ]
    query = s.derive_product_query([{"title": t} for t in titles])
    assert query.split()[:3] == ["nike", "pegasus", "41"]
    assert "buy" not in query and "price" not in query


def test_derive_product_query_without_titles():
    assert s.derive_product_query([]) == ""


@pytest.mark.parametrize(
    "url, kind",
    [
        ("https://www.amazon.in/Some-Watch/dp/B0H7NB27B6", "product"),
        ("https://www.flipkart.com/watch/p/itm69d03b648e996", "product"),
        ("https://www.myntra.com/watches/otage/otage-men/123456/buy", "product"),
        ("https://www.tatacliq.com/casio-g-shock/p-mp000000012345", "product"),
        ("https://www.etsy.com/in-en/listing/1868522296/foxbox", "product"),
        ("https://finebuy.co.in/ts_mega_menu/accessories-menu-wide/", "listing"),
        ("https://www.shutterstock.com/search/g-shock-brand", "listing"),
        ("https://casiofanmag.com/news/g-shock-review/", "listing"),
        ("https://example-shop.com/", "listing"),
        ("https://www.swisstimehouse.com/casio-g1705", None),
    ],
)
def test_classify_listing_url(url, kind):
    assert s.classify_listing_url(url) == kind


@pytest.mark.parametrize(
    "url, indian",
    [
        ("https://finebuy.co.in/product/x", True),
        ("https://www.flipkart.com/x/p/itm1", True),
        ("https://www.lifestylestores.com/in/en/x/p/1", True),
        ("https://www.casio.com/us/watches/", False),
        ("https://www.strobl.cz/el/watch_p1", False),
    ],
)
def test_is_indian_store(url, indian):
    assert s.is_indian_store(url) is indian


def listing(title, link, lens_price=None, page=None):
    item = {"title": title, "link": link, "source": "store"}
    if lens_price:
        item["price"] = lens_price
    if page is not None:
        item["_page_details"] = page
    item["_offer"] = s.resolve_offer(item)
    return item


RUPEES = {"value": "₹999", "extracted_value": 999, "currency": "₹"}
EUROS = {"value": "€25", "extracted_value": 25, "currency": "€"}
CHECKED_NOTHING = {"fetched": True, "is_product_page": False}
BLOCKED = {"fetched": False}


@pytest.mark.parametrize(
    "item, keep",
    [
        (listing("Watch", "https://www.amazon.in/x/dp/A", RUPEES), True),
        (listing("Accessories – Menu Wide", "https://finebuy.co.in/menu/", page=CHECKED_NOTHING), False),
        (listing("G-Shock review", "https://blog.example/news/x/", page=CHECKED_NOTHING), False),
        (listing("Watch", "https://www.strobl.cz/el/watch_p1", EUROS), False),
        (listing("Watch", "https://jiji.co.ke/watch.html", page=BLOCKED), False),
        (listing("Watch", "https://www.aliexpress.com/item/1.html", RUPEES), True),
        (listing("Watch", "https://www.etsy.com/in-en/listing/1/watch", page=BLOCKED), True),
    ],
)
def test_listing_filters(item, keep):
    assert (s.looks_like_product_page(item) and s.is_available_in_india(item)) is keep


def test_select_sections_marks_pending_in_preview():
    candidates = [
        listing("Priced and stocked", "https://www.amazon.in/a/dp/A",
                {**RUPEES, "extracted_value": 500}),
        listing("No price yet", "https://www.flipkart.com/b/p/itm1"),
    ]
    candidates[0]["in_stock"] = True

    preview = s.select_sections(candidates, max_results=10, preview=True)
    pending = {p["name"]: p["pending"] for p in preview["best_matches"]}
    assert pending == {"Priced and stocked": False, "No price yet": True}

    final = s.select_sections(candidates, max_results=10)
    assert all(p["pending"] is False for p in final["best_matches"])


def test_missing_prices_are_filled_from_the_same_store_on_google_shopping():
    from concurrent.futures import Future
    import time

    candidates = [
        {"title": "Buy Soch Women Floral Printed Kurta - Kurtas for Women", "source": "Myntra",
         "link": "https://www.myntra.com/kurtas/soch/123"},
        {"title": "Soch Women Floral Kurta", "source": "Ajio", "link": "https://www.ajio.com/p/9"},
        {"title": "Unrelated Blue Jeans", "source": "Myntra", "link": "https://www.myntra.com/jeans/1"},
        {"title": "Soch Floral Kurta", "source": "Flipkart", "link": "https://www.flipkart.com/p/1",
         "price": {"value": "₹999", "extracted_value": 999, "currency": "₹"}},
    ]
    job = Future()
    job.set_result([
        {"title": "Soch Women Floral Printed Kurta", "source": "Myntra", "price": "₹1,403"},
        {"title": "Soch Women Floral Printed Kurta", "source": "Amazon.in", "price": "₹1,200"},
        {"title": "Soch Floral Kurta", "source": "Flipkart", "price": "₹1,500"},
    ])

    filled = s.apply_shopping_prices(candidates, job, time.monotonic() + 1)

    assert filled == 1
    assert candidates[0]["_shopping_price"]["price"] == 1403  # same store, same product
    assert "_shopping_price" not in candidates[1]  # Ajio isn't in the Shopping results
    assert "_shopping_price" not in candidates[2]  # same store, different product
    assert "_shopping_price" not in candidates[3]  # already had a Lens price
    assert s.resolve_offer(candidates[0])["price"] == 1403


def test_no_shopping_lookup_without_serper():
    assert s.start_shopping_prices("soch kurta") is None


def test_photo_search_shows_lens_order_first_then_ranked(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "VISUAL_RERANK", True)
    candidates = [
        {"title": f"Watch {name}", "source": "Flipkart", "link": f"https://www.flipkart.com/w/p/{name}",
         "thumbnail": f"https://img.example/{name}.jpg",
         "price": {"value": f"₹{price}", "extracted_value": price, "currency": "₹"}, "in_stock": True}
        for name, price in (("a", 900), ("b", 800), ("c", 700))
    ]
    monkeypatch.setattr(s, "run_google_lens", lambda path, query=None: [dict(c) for c in candidates])
    monkeypatch.setattr(
        s, "download_and_score",
        lambda path, items, on_downloaded=None: ([None] * len(items), {0: 0.5, 1: 0.9, 2: 0.7}),
    )
    monkeypatch.setattr(s, "start_page_details", lambda items, deadline=None: None)
    monkeypatch.setattr(s, "finish_page_details", lambda job: None)

    events = []
    s.search_products_by_image(tmp_path / "photo.jpg", on_event=lambda kind, data: events.append((kind, data)))

    previews = [data for kind, data in events if kind == "preview"]
    assert [p["ranked"] for p in previews] == [False, True]
    assert [p["name"] for p in previews[0]["best_matches"]] == ["Watch a", "Watch b", "Watch c"]
    assert [p["name"] for p in previews[1]["best_matches"]] == ["Watch b", "Watch c", "Watch a"]


def test_foreign_listings_dont_crowd_out_indian_ones(monkeypatch, tmp_path):
    foreign = [
        {"title": f"Shirt {i}", "source": "Shop", "link": f"https://shop.example.com/p/{i}",
         "price": {"value": f"${20 + i}", "extracted_value": 20 + i, "currency": "$"}}
        for i in range(30)
    ]
    indian = [
        {"title": "Cotton Shirt", "source": "Myntra", "link": "https://www.myntra.com/shirts/x/1/buy",
         "price": {"value": "₹799", "extracted_value": 799, "currency": "₹"}, "in_stock": True},
    ]
    monkeypatch.setattr(s, "run_google_lens", lambda path, query=None: foreign + indian)
    monkeypatch.setattr(
        s, "download_and_score", lambda path, items, on_downloaded=None: ([None] * len(items), {})
    )
    monkeypatch.setattr(s, "start_page_details", lambda items, deadline=None: None)
    monkeypatch.setattr(s, "finish_page_details", lambda job: None)

    result = s.search_products_by_image(tmp_path / "photo.jpg")
    assert [p["name"] for p in result["best_matches"]] == ["Cotton Shirt"]


def test_download_and_score_scores_thumbnails_in_groups(monkeypatch):
    import numpy as np
    from PIL import Image

    monkeypatch.setattr(s, "load_clip_model", lambda: (object(), object()))
    monkeypatch.setattr(s, "download_thumbnail", lambda url: Image.new("RGB", (4, 4)) if url else None)

    batches = []

    def fake_encode(model, processor, images):
        batches.append(len(images))
        # The photo is encoded first: its row is [1, 0]. Each thumbnail is a
        # unit vector at an angle to it, so its similarity is 0.6.
        if len(batches) == 1:
            return np.array([[1.0, 0.0]])
        return np.array([[0.6, 0.8]] * len(images))

    monkeypatch.setattr(s, "encode_images", fake_encode)

    candidates = [{"thumbnail": f"https://img.example/{i}.jpg"} for i in range(11)]
    candidates.append({"thumbnail": None})
    downloaded = []

    thumbnails, scores = s.download_and_score(
        Image.new("RGB", (4, 4)), candidates, on_downloaded=lambda: downloaded.append(True)
    )

    assert downloaded == [True]
    assert sorted(scores) == list(range(11))  # the candidate without a thumbnail is unscored
    assert all(score == 0.6 for score in scores.values())
    assert thumbnails[11] is None and thumbnails[0] is not None
    assert batches[0] == 1 and sum(batches[1:]) == 11  # photo first, then thumbnails in groups


def test_download_and_score_without_clip_just_downloads(monkeypatch):
    monkeypatch.setattr(s, "load_clip_model", lambda: (None, None))
    monkeypatch.setattr(s, "download_thumbnails", lambda items, deadline=None: ["img"] * len(items))
    called = []

    thumbnails, scores = s.download_and_score(
        "photo.jpg", [{"thumbnail": "x"}, {"thumbnail": "y"}], on_downloaded=lambda: called.append(1)
    )

    assert thumbnails == ["img", "img"] and scores == {} and called == [1]



def dupe_item(name, price, similarity):
    item = {
        "title": name, "source": "Myntra", "link": f"https://www.myntra.com/p/{name}",
        "price": {"value": f"₹{price}", "extracted_value": price, "currency": "₹"},
        "in_stock": True, "_visual_similarity_score": similarity,
    }
    item["_offer"] = s.resolve_offer(item)
    return item


def test_find_dupes_picks_cheap_lookalikes():
    kept = [
        dupe_item("original-a", 4000, 0.95),
        dupe_item("original-b", 3800, 0.93),
        dupe_item("original-c", 4200, 0.92),
        dupe_item("lookalike", 1200, 0.86),  # similar and 70% cheaper
        dupe_item("cheap-but-different", 500, 0.62),  # not similar enough
        dupe_item("similar-not-cheap", 3500, 0.88),  # not cheap enough
        dupe_item("another-lookalike", 900, 0.81),
    ]

    dupes = s.find_dupes(kept)

    assert [(item["title"], reference) for item, reference in dupes] == [
        ("another-lookalike", 4000),
        ("lookalike", 4000),
    ]


def test_select_sections_reports_dupes_with_savings():
    kept = [dupe_item(f"original-{i}", 3000, 0.95 - i / 100) for i in range(3)] + [dupe_item("lookalike", 999, 0.85)]
    sections = s.select_sections(kept, max_results=10)
    assert [d["name"] for d in sections["dupes"]] == ["lookalike"]
    assert sections["dupes"][0]["dupe_savings"] == 2001

    assert s.select_sections(kept, max_results=10, preview=True)["dupes"] == []


def test_preprocessing_matches_the_clip_reference_shape_and_scale():
    from PIL import Image

    pixels = s.preprocess_images([Image.new("RGB", (500, 300), (255, 255, 255)), Image.new("RGB", (40, 90))])

    assert pixels.shape == (2, 3, 224, 224) and pixels.dtype.name == "float32"
    # white maps to (1 - mean) / std on each channel
    assert abs(float(pixels[0, 0, 0, 0]) - (1 - s.CLIP_MEAN[0]) / s.CLIP_STD[0]) < 1e-5


def test_the_bundled_model_loads_and_scores_an_image_against_itself():
    from PIL import Image

    model, processor = s.load_clip_model()
    if model is None:
        pytest.skip("onnxruntime is not installed")
    features = s.encode_images(model, processor, [Image.new("RGB", (64, 64), (200, 30, 30))] * 2)

    assert features.shape == (2, 512)
    assert abs(float(features[0] @ features[1]) - 1.0) < 1e-4

