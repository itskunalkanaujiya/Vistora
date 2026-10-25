import pytest

import image_shopping_service as s


def listing(title, price=999, source="Flipkart", slug=None):
    slug = slug or title.lower().replace(" ", "-")[:30]
    item = {"title": title, "source": source, "link": f"https://www.flipkart.com/{slug}/p/{abs(hash(title)) % 10**6}",
            "thumbnail": f"https://img.example/{slug}.jpg", "in_stock": True}
    if price is not None:
        item["price"] = {"value": f"₹{price}", "extracted_value": price, "currency": "₹"}
    return item


# --- accessories ---------------------------------------------------------------------------


@pytest.mark.parametrize("title", [
    "VERTUS Premium Tempered Glass Screen Protector for Casio F-91W",
    "HEPOCH Screen Guard for Casio Youth Series Digital Black",
    "AWINNER Headband Cover Compatible for Apple AirPods Max",
    "ProElite Slim Smart Flip case Cover for Amazon Kindle",
    "Hyphen Series 7 Apple Watch Protector",
    "AirPods Max Skins, Wraps & Covers",
    "Silicone Strap Band for Apple Watch Series 8",
    "Replacement Ear Pads Cushions for Sony headphones",
])
def test_accessories_for_a_product_are_recognised(title):
    assert s.ACCESSORY_TITLE_PATTERN.search(title)


@pytest.mark.parametrize("title", [
    "Casio F-91W-1Q Black Digital Unisex Watch",
    "Men Cotton Full Sleeve T-Shirt",
    "Women Lace-up Sneakers White",
    "Cable Knit Sweater for Men",
    "Stand Collar Slim Fit Shirt",
    "Apple AirPods Max Wireless Over-Ear Headphones",
    "Nike Air Force 1 '07 Sneaker, White",
    "Logitech MX Master 3S Wireless Mouse",
    "Slim Fit Jeans for Men",
])
def test_real_products_and_clothing_are_not_mistaken_for_accessories(title):
    assert not s.ACCESSORY_TITLE_PATTERN.search(title)


def test_accessories_are_dropped_from_the_listings():
    items = [listing("Casio F-91W Digital Watch"), listing("Screen Guard for Casio F-91W"),
             listing("Silicone Strap Band for Casio F-91W")]

    kept = s.drop_accessories(items, "casio f-91w digital watch")

    assert [i["title"] for i in kept] == ["Casio F-91W Digital Watch"]


def test_a_phrase_naming_the_shopper_is_not_an_accessory():
    # "for Men" names who it is for, not which product it fits.
    assert not s.ACCESSORY_TITLE_PATTERN.search("Digital Strap Style Watch for Men")
    assert not s.ACCESSORY_TITLE_PATTERN.search("Cable Knit Sweater for Women")


def test_nothing_is_dropped_when_the_photographed_product_is_an_accessory():
    items = [listing("Silicone Case for iPhone 15"), listing("Tempered Glass Screen Protector for iPhone 15")]

    assert s.drop_accessories(items, "iphone 15 silicone case") == items


def test_nothing_is_dropped_if_that_would_leave_nothing():
    items = [listing("Screen Guard for Casio F-91W")]

    assert s.drop_accessories(items, "casio watch") == items


# --- news pages -------------------------------------------------------------------------------


def test_news_pages_without_a_price_are_not_products():
    for title in ["New Kindle Paperwhite launched in India, Amazon says",
                  "Samsung Galaxy Buds+ leaked in hands-on video",
                  "Everything you need to know about the Casio F-91W"]:
        assert s.NON_PRODUCT_TITLE_PATTERN.search(title), title


def test_news_pages_are_left_out_of_the_sections():
    candidates = [listing("Kindle Paperwhite 16 GB", price=13999),
                  listing("New Kindle Paperwhite launched in India", price=None, source="Gadgets News", slug="news")]
    for item in candidates:
        item["_text_relevance_score"] = 1.0

    sections = s.select_sections(candidates, 10, query="kindle paperwhite")

    names = [p["name"] for p in sections["best_matches"]]
    assert names == ["Kindle Paperwhite 16 GB"]


# --- the order of the results -----------------------------------------------------------------------


@pytest.fixture
def search(monkeypatch, tmp_path):
    from PIL import Image

    def run(candidates, scores, query):
        monkeypatch.setattr(s, "run_google_lens", lambda path, query=None: [dict(c) for c in candidates])
        monkeypatch.setattr(s, "download_and_score", lambda path, items, on_downloaded=None: ([None] * len(items), scores))
        monkeypatch.setattr(s, "start_page_details", lambda items, deadline=None: None)
        monkeypatch.setattr(s, "finish_page_details", lambda job: None)
        photo = tmp_path / "photo.jpg"
        Image.new("RGB", (50, 50)).save(photo)
        events = []
        result = s.search_products_by_image(photo, on_event=lambda kind, data: events.append((kind, data)), query=query)
        return result, events

    return run


def test_the_listing_that_names_the_product_beats_a_better_looking_one(search):
    candidates = [
        listing("Generic Digital Sports Watch Black", slug="generic"),
        listing("Casio F-91W Digital Watch", slug="casio"),
        listing("Casio F-91W-1Q Classic Digital Watch", slug="casio2"),
    ]
    # The generic watch looks most like the photo, but does not name the product.
    scores = {0: 0.95, 1: 0.80, 2: 0.78}

    result, events = search(candidates, scores, "casio f-91w digital watch")

    names = [p["name"] for p in result["best_matches"]]
    assert names[0].startswith("Casio F-91W") and names[-1] == "Generic Digital Sports Watch Black"


def test_visual_similarity_still_breaks_ties_between_equally_named_listings(search):
    candidates = [listing("Casio F-91W Digital Watch", slug="a"), listing("Casio F-91W Digital Watch", slug="b")]
    scores = {0: 0.70, 1: 0.90}

    result, _ = search(candidates, scores, "casio f-91w digital watch")

    assert [p["visual_similarity_score"] for p in result["best_matches"]] == [0.9, 0.7]


def test_the_ranked_preview_uses_the_same_order_as_the_final_results(search):
    candidates = [listing("Generic Watch", slug="g"), listing("Casio F-91W Digital Watch", slug="c")]

    result, events = search(candidates, {0: 0.9, 1: 0.7}, "casio f-91w digital watch")

    ranked = [d for kind, d in events if kind == "preview" and d["ranked"]][0]
    assert [p["name"] for p in ranked["best_matches"]] == [p["name"] for p in result["best_matches"]]
