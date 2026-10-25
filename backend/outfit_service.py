"""
Find the outfit: identify everything a person in a photo is wearing, then
find shopping options for each item.

A vision model lists the clothing and accessories, head to toe, with a
shopping description and a box for each. Gemini Flash (Google AI Studio's
free tier) is used when GEMINI_API_KEY is set, as it finds more items and
places boxes better; otherwise, or if it fails, Qwen3.8 27B on Groq. The
photo is padded to a square first, so both models' coordinates mean the
same thing on portrait and landscape photos.

Every item is then searched on Google Shopping (the text search pipeline,
through Serper) in parallel, so a whole outfit costs no Google Lens
searches. The listings are re-ranked by how much their photos look like
the item's crop from the photo (CLIP), and clear mismatches are dropped.

Complete the look works the same way from a product instead of a photo: a
text model suggests the items that go with it (shoes and a belt for a
shirt, a bag and a mouse for a laptop), and each is searched in parallel.
"""

import base64
import io
import json
import os
import re
import time
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image, ImageOps

from listing_judge import judge_listings
from llm_query_parser import GROQ_URL, chat_json
import image_shopping_service
from image_shopping_service import compute_visual_similarity_scores, download_thumbnails, load_clip_model
from text_shopping_service import search_products_by_text

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# Tried in order; a model Google has retired (404) or that is overloaded
# (503) is skipped. Low thinking keeps answers to a few seconds.
GEMINI_MODELS = [
    model
    for model in (os.getenv("GEMINI_MODEL"), "gemini-3.5-flash", "gemini-3.5-flash-lite")
    if model
]
VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
VISION_IMAGE_SIZE = 1024  # enough detail for earrings and watches
VISION_TIMEOUT_SECONDS = 25
PAD_COLOUR = (127, 127, 127)
MIN_BOX_SIZE = 0.015  # boxes smaller than this (of the photo) are noise
MAX_ITEMS = 8
RESULTS_PER_ITEM = 8
CHEAPER_PER_ITEM = 4
# Listings fetched per item before they're re-ranked against the item's crop.
SEARCH_POOL = 24
CROP_PADDING = 0.08  # share of the box added on each side
MIN_CROP_PIXELS = 24
# CLIP similarity between an item's crop and a listing photo depends on the
# item (small crops like rings score lower overall), so listings are judged
# against the best one: more than SIMILARITY_GAP below it looks clearly
# different (a plain shirt for a printed one) and is dropped, keeping at
# least MIN_KEPT.
SIMILARITY_GAP = 0.08
MIN_KEPT = 4
# Listings priced above this multiple of the item's typical price (a
# ₹5 lakh designer skirt among ₹1,500 ones) are left out.
MAX_PRICE_FACTOR = 4
# Seven items fetch their listing photos at once; allow for that.
THUMBNAIL_DEADLINE = 5
# Long descriptions ("maroon white heart print long sleeve shirt") rarely
# match listing titles word for word ("wristwatch" vs "watch"), so Google's
# results are trusted when the listings will be compared with the crop.
LOOSE_RELEVANCE = 0.1
LOOK_ITEMS = 4
LOOK_TIMEOUT_SECONDS = 10
GENDERS = {"men", "women", "boys", "girls", "kids", "unisex"}

PROMPT = """You are a fashion expert for an Indian shopping app.
Look carefully at the main person in the photo, from head to toe, and list every item they wear or carry that a shopper could buy.

Check each of these and include every one that is visible, even if small:
- headwear: cap, hat, beanie, turban, hair band, maang tikka
- eyewear: sunglasses, spectacles
- jewellery: earrings, nose ring, necklace, chain, pendant, bangles, bracelet, kada, ring
- outerwear: jacket, blazer, coat, shrug, cardigan
- top: shirt, t-shirt, top, blouse, sweater, hoodie, kurta, kurti, dress, gown
- drapes: dupatta, stole, scarf, saree, veil
- bottom: jeans, trousers, chinos, shorts, skirt, salwar, palazzo, leggings, lehenga, dhoti
- belt, watch, bag (handbag, backpack, sling bag, clutch, tote)
- footwear: sneakers, shoes, loafers, heels, sandals, flats, juttis, mojaris, boots

Return JSON only:
{
  "gender": "men" | "women" | "boys" | "girls" | "kids" | "unisex",
  "items": [
    {
      "type": short category from the list above, e.g. "shirt", "sunglasses", "jhumka earrings",
      "description": a 4-10 word shopping search: colour, pattern, material, fit or style, then the item, e.g. "maroon white heart print silk shirt",
      "box": BOX_FORMAT
    }
  ]
}
Rules:
- Only things the person wears or carries: not body parts, hair, tattoos, mehendi, background or other people.
- One entry per item: a pair of shoes or earrings is one item; several bangles on one arm are one item.
- Skip anything you cannot see (feet cut off means no footwear).
- Name a brand only if its logo or name is clearly readable on the item.
- At most 8 items, most noticeable first.
- If no person is visible, return {"gender": "unisex", "items": []}."""

# How each model family writes boxes. Gemini is trained on [ymin, xmin,
# ymax, xmax]; Qwen on [x1, y1, x2, y2]. Both use 0-1000 of the image.
BOX_FORMATS = {
    "xyxy": "[x1, y1, x2, y2] tightly around just this item, each from 0 to 1000 of the image width (x) and height (y)",
    "yxyx": "[ymin, xmin, ymax, xmax] tightly around just this item, each from 0 to 1000 of the image height (y) and width (x)",
}

LOOK_PROMPT = """You are a stylist for an Indian shopping app.
The customer is looking at one product. Suggest the other items that go best with it.
Return JSON only:
{
  "gender": "men" | "women" | "boys" | "girls" | "kids" | "unisex",
  "items": [
    {
      "type": short category, e.g. "chinos", "loafers", "leather belt", "laptop bag",
      "description": a 3-8 word shopping search with colour, style and material that matches the product, e.g. "tan leather slip-on loafers",
      "reason": under 12 words on why it goes well, e.g. "Tan leather keeps the navy shirt smart but relaxed",
      "price_range": [lowest, highest] sensible price in rupees for this item at the same price level as the product, e.g. [800, 2500]
    }
  ]
}
Rules:
- 3 or 4 items, most useful first, each a different type, none the same type as the product.
- Clothing: complete a wearable outfit (bottom or top, footwear, one or two accessories) in colours that suit the product.
- Anything else (a laptop, phone, kitchen item): suggest the accessories people usually buy with it.
- No brands unless the product's brand makes its own matching accessories.
- Gender from the product name; "unisex" if unclear."""


class OutfitError(Exception):
    """An outfit couldn't be identified; the message is safe to show users."""

    user_facing = True


def vision_providers():
    """The vision models to try, best first: (name, url, api key, models, box order)."""
    providers = []
    if os.getenv("GEMINI_API_KEY"):
        providers.append(("Gemini", GEMINI_URL, os.environ["GEMINI_API_KEY"], GEMINI_MODELS, "yxyx"))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("Groq", GROQ_URL, os.environ["GROQ_API_KEY"], [VISION_MODEL], "xyxy"))
    return providers


def square_photo(image):
    """
    The photo shrunk to VISION_IMAGE_SIZE and centred on a square canvas,
    with the frame (left, top, width, height, side) needed to map boxes back.
    """
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((VISION_IMAGE_SIZE, VISION_IMAGE_SIZE))
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), PAD_COLOUR)
    left, top = (side - width) // 2, (side - height) // 2
    canvas.paste(image, (left, top))
    return canvas, (left, top, width, height, side)


def _data_url(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _box(value, frame, order="xyxy"):
    """
    A model box (0-1000 of the square) as fractions of the original photo
    [x1, y1, x2, y2], or None if unusable.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = [min(1000.0, max(0.0, float(v))) / 1000 for v in value]
    except (TypeError, ValueError):
        return None
    if order == "yxyx":
        numbers = [numbers[1], numbers[0], numbers[3], numbers[2]]
    left, top, width, height, side = frame

    def unpad(fraction, offset, size):
        return min(1.0, max(0.0, (fraction * side - offset) / size))

    x1, x2 = sorted(unpad(n, left, width) for n in (numbers[0], numbers[2]))
    y1, y2 = sorted(unpad(n, top, height) for n in (numbers[1], numbers[3]))
    if x2 - x1 < MIN_BOX_SIZE or y2 - y1 < MIN_BOX_SIZE:
        return None
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def _clean(text, limit):
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()[:limit]


# A model that just failed (retired, out of quota, overloaded or too slow) is
# skipped for a while, so one bad model doesn't add its wait to every search.
SKIP_SECONDS = {404: 3600, 429: 600, 503: 120, "slow": 120}
_skip_until = {}


def _skip(model, reason):
    _skip_until[model] = time.monotonic() + SKIP_SECONDS[reason]


def ask_vision_model(
    url, api_key, models, prompt, photo_url, max_tokens=1400, effort="low", timeout=VISION_TIMEOUT_SECONDS
):
    """The first available model's JSON answer about the photo. Raises OutfitError."""
    busy = False
    unreachable = False
    now = time.monotonic()
    # If every model was recently skipped, try them all anyway.
    models = [m for m in models if _skip_until.get(m, 0) <= now] or models
    for model in models:
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": photo_url}},
                ],
            }],
        }
        if url == GEMINI_URL:
            payload["reasoning_effort"] = effort
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            print(f"Outfit model request failed ({model}): {exc}")
            _skip(model, "slow")
            unreachable = True
            continue

        if response.status_code in (404, 503):
            print(f"Vision model {model} is not available ({response.status_code}); trying the next one.")
            _skip(model, response.status_code)
            continue
        if response.status_code == 429:
            # Out of quota or busy: another model in the list may still answer.
            print(f"Vision model {model} is busy (429); trying the next one.")
            _skip(model, 429)
            busy = True
            continue
        if response.status_code != 200:
            print(f"Outfit model error {response.status_code} ({model}): {response.text[:300]}")
            raise OutfitError("Couldn't identify the outfit. Please try again.")

        try:
            content = response.json()["choices"][0]["message"]["content"]
            # Some models wrap JSON in a code fence despite the JSON mode.
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return data
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            print(f"Outfit model returned unreadable output ({model}): {exc}")
            raise OutfitError("Couldn't identify the outfit. Please try another photo.")

    if busy:
        raise OutfitError("The outfit AI is busy right now. Please try again in a minute.")
    if unreachable:
        raise OutfitError("Couldn't reach the outfit AI. Please try again.")
    raise OutfitError("Couldn't identify the outfit. Please try again.")


def read_outfit(data, frame, order):
    """The model's answer as {"gender", "items": [{"id", "type", "description", "box"}]}."""
    gender = _clean(data.get("gender"), 10).lower()
    items, seen = [], set()
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item_type = _clean(raw.get("type"), 30).lower()
        description = _clean(raw.get("description"), 90)
        if not item_type or not description or description.lower() in seen:
            continue
        seen.add(description.lower())
        items.append({
            "id": f"item-{len(items) + 1}",
            "type": item_type,
            "description": description,
            "box": _box(raw.get("box") or raw.get("box_2d"), frame, order),
        })
        if len(items) == MAX_ITEMS:
            break
    return {"gender": gender if gender in GENDERS else "unisex", "items": items}


def ask_vision(
    image,
    prompt,
    not_set_up="Find the outfit isn't set up on this server yet.",
    gemini_models=None,
    **options,
):
    """
    Ask the best available vision model about a photo; returns (answer,
    frame, box order, provider name). "BOX_FORMAT" in the prompt becomes the
    provider's box format. Tries each provider in turn; raises OutfitError
    with a user-facing message if none can answer. gemini_models replaces the
    default Gemini model list; options (max_tokens, effort, timeout) go to
    ask_vision_model.
    """
    providers = vision_providers()
    if not providers:
        raise OutfitError(not_set_up)

    square, frame = square_photo(image)
    photo_url = _data_url(square)
    error = None
    for name, url, api_key, models, order in providers:
        try:
            answer = ask_vision_model(
                url,
                api_key,
                gemini_models if url == GEMINI_URL and gemini_models else models,
                prompt.replace("BOX_FORMAT", BOX_FORMATS[order]),
                photo_url,
                **options,
            )
        except OutfitError as exc:
            print(f"{name} could not answer: {exc}")
            error = exc
            continue
        return answer, frame, order, name
    raise error


def identify_outfit(image):
    """
    The items the main person wears: {"gender", "items": [{"id", "type",
    "description", "box"}], "model"}. Raises OutfitError.
    """
    answer, frame, order, name = ask_vision(image, PROMPT)
    outfit = read_outfit(answer, frame, order)
    outfit["model"] = name
    return outfit


def item_query(item, gender):
    """The shopping search for one item, e.g. "men dark blue slim fit jeans"."""
    description = item["description"]
    if gender in GENDERS - {"unisex"} and gender not in description.lower():
        return f"{gender} {description}"
    return description


def _emitter(on_event):
    def emit(event_type, payload):
        if on_event is not None:
            try:
                on_event(event_type, payload)
            except Exception as exc:
                print(f"Outfit event handler failed: {exc}")

    return emit


def crop_item(image, box):
    """The item's region of the photo (with a little margin), or None."""
    if not box or image is None:
        return None
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    x1, y1, x2, y2 = box
    pad_x, pad_y = (x2 - x1) * CROP_PADDING, (y2 - y1) * CROP_PADDING
    left, top = max(0, (x1 - pad_x) * width), max(0, (y1 - pad_y) * height)
    right, bottom = min(width, (x2 + pad_x) * width), min(height, (y2 + pad_y) * height)
    if right - left < MIN_CROP_PIXELS or bottom - top < MIN_CROP_PIXELS:
        return None
    return image.crop((round(left), round(top), round(right), round(bottom)))


def unique_listings(result):
    seen, listings = set(), []
    for product in (result.get("best_matches") or []) + (result.get("cheapest_alternatives") or []):
        key = product.get("product_url") or product.get("name")
        if key not in seen:
            seen.add(key)
            listings.append(product)
    return listings


def rank_by_look(crop, result):
    """
    Order an item's listings by how much their photos look like the item's
    crop, dropping clear mismatches. Returns (best_matches, cheapest).
    """
    listings = unique_listings(result)
    scores = {}
    if crop is not None and listings:
        thumbnails = download_thumbnails(
            [{"thumbnail": p.get("image_url")} for p in listings], deadline=THUMBNAIL_DEADLINE
        )
        scores = compute_visual_similarity_scores(crop, listings, thumbnails=thumbnails)

    if not scores:
        # No crop or no CLIP: keep the text search's own order.
        best = (result.get("best_matches") or [])[:RESULTS_PER_ITEM]
        cheapest = (result.get("cheapest_alternatives") or [])[:CHEAPER_PER_ITEM]
        return best, cheapest

    for index, product in enumerate(listings):
        product["visual_similarity_score"] = scores.get(index)
    prices = [p["price"] for p in listings if p.get("price")]
    typical = statistics.median(prices) if len(prices) >= MIN_KEPT else None
    scored = sorted(
        (
            p for p in listings
            if p["visual_similarity_score"] is not None
            and not (typical and p.get("price") and p["price"] > MAX_PRICE_FACTOR * typical)
        ),
        key=lambda p: -p["visual_similarity_score"],
    )
    if not scored:
        best = (result.get("best_matches") or [])[:RESULTS_PER_ITEM]
        return best, (result.get("cheapest_alternatives") or [])[:CHEAPER_PER_ITEM]
    floor = scored[0]["visual_similarity_score"] - SIMILARITY_GAP
    alike = [p for p in scored if p["visual_similarity_score"] >= floor]
    kept = alike if len(alike) >= MIN_KEPT else scored[:MIN_KEPT]
    if len(kept) < MIN_KEPT:
        # Listings whose photo didn't load follow, in Google's order.
        unscored = [p for p in result.get("best_matches") or [] if p.get("visual_similarity_score") is None]
        kept += unscored[:MIN_KEPT - len(kept)]

    best = kept[:RESULTS_PER_ITEM]
    shown = {id(p) for p in best}
    cheapest = sorted(
        (p for p in kept if id(p) not in shown and p.get("price") is not None),
        key=lambda p: p["price"],
    )[:CHEAPER_PER_ITEM]
    # Crop scores run lower than whole-photo scores, so they'd read as weak
    # "match" badges on the cards; they're only used for ordering here.
    for product in listings:
        product.pop("visual_similarity_score", None)
    return best, cheapest


def judged_sections(item, result, gender):
    """A suggested item's listings checked by the judge: (best_matches, cheapest)."""
    picked = judge_listings(item, unique_listings(result), gender)
    best = picked[:RESULTS_PER_ITEM]
    shown = {id(p) for p in best}
    cheapest = sorted(
        (p for p in picked if id(p) not in shown and p.get("price") is not None),
        key=lambda p: p["price"],
    )[:CHEAPER_PER_ITEM]
    return best, cheapest


def visual_ranking_available():
    """Whether CLIP is on, so listings can be compared with an item's crop."""
    return image_shopping_service.CLIP_AVAILABLE and image_shopping_service.ENABLE_CLIP_RANKING


def shop_items(items, gender, emit, image=None, judge=False):
    """
    Search every item in parallel, adding its results; emits "item" each.
    With the photo, each item's listings are re-ranked against its crop;
    with judge, suggested items' listings are checked by a language model.
    """
    for item in items:
        item["query"] = item_query(item, gender)
    emit("items", {"gender": gender, "items": items})

    def search(item):
        try:
            crop = crop_item(image, item.get("box"))
            # The description is already a clean search; skip the text model.
            # The wide, loose search only pays off when CLIP then filters it by look.
            if (crop is not None and visual_ranking_available()) or judge:
                result = search_products_by_text(
                    item["query"], SEARCH_POOL, understand=False, min_relevance=LOOSE_RELEVANCE
                )
            else:
                result = search_products_by_text(item["query"], RESULTS_PER_ITEM, understand=False)
            if crop is None and judge:
                return item, judged_sections(item, result, gender), None
            return item, rank_by_look(crop, result), None
        except Exception as exc:
            print(f"Outfit item search failed for {item['query']!r}: {exc}")
            return item, ([], []), exc

    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        for future in as_completed([pool.submit(search, item) for item in items]):
            item, (best, cheapest), error = future.result()
            item["best_matches"] = best
            item["cheapest_alternatives"] = cheapest
            item["failed"] = error is not None
            emit("item", {"item": item})

    return {"gender": gender, "items": items}


def find_outfit(image, on_event=None):
    """
    Identify the outfit, then search every item in parallel.

    on_event(event_type, payload) is called with "items" once the outfit is
    identified and "item" as each item's results arrive. Returns
    {"gender", "items": [{..., "query", "best_matches", "cheapest_alternatives"}]}.
    """
    # Load the image model while the vision model looks at the photo.
    threading.Thread(target=load_clip_model, daemon=True).start()
    outfit = identify_outfit(image)
    if not outfit["items"]:
        raise OutfitError("Couldn't find a person's outfit in this photo. Try a clear photo of someone.")
    result = shop_items(outfit["items"], outfit["gender"], _emitter(on_event), image=image)
    result["model"] = outfit.get("model")
    return result


def price_range(value):
    """A model's [low, high] rupee range, or None if unusable."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        low, high = sorted(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return [round(low), round(high)] if high > 0 else None


def suggest_look(product_name, product_price=None):
    """
    The items that go with a product: {"gender", "items": [{"id", "type",
    "description", "reason", "box": None}]}. Raises OutfitError.
    """
    if not os.getenv("GROQ_API_KEY"):
        raise OutfitError("Complete the look isn't set up on this server yet.")

    try:
        data = chat_json(
            [
                {"role": "system", "content": LOOK_PROMPT},
                {"role": "user", "content": f"Product: {product_name}" + (
                    f" (₹{product_price:,.0f})" if product_price else ""
                )},
            ],
            max_tokens=700,
            timeout=LOOK_TIMEOUT_SECONDS,
            temperature=0.3,
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise OutfitError("The styling AI is busy right now. Please try again in a minute.")
        print(f"Look model error: {exc}")
        raise OutfitError("Couldn't put a look together. Please try again.")
    except Exception as exc:
        print(f"Look model failed: {exc}")
        raise OutfitError("Couldn't put a look together. Please try again.")

    gender = _clean(data.get("gender"), 10).lower()
    product_words = set(re.findall(r"[a-z]+", product_name.lower()))
    items, types = [], set()
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        item_type = _clean(raw.get("type"), 30).lower()
        description = _clean(raw.get("description"), 80)
        # Skip repeats, and the product's own type ("shirt" for a shirt).
        if not item_type or not description or item_type in types:
            continue
        if set(item_type.split()) <= product_words:
            continue
        types.add(item_type)
        items.append({
            "id": f"look-{len(items) + 1}",
            "type": item_type,
            "description": description,
            "reason": _clean(raw.get("reason"), 100),
            "price_range": price_range(raw.get("price_range")),
            "box": None,
        })
        if len(items) == LOOK_ITEMS:
            break

    return {"gender": gender if gender in GENDERS else "unisex", "items": items}


def complete_the_look(product_name, on_event=None, product_price=None):
    """Suggest what goes with a product, then search each item in parallel."""
    look = suggest_look(product_name, product_price)
    if not look["items"]:
        raise OutfitError("Couldn't find items to go with this product.")
    return shop_items(look["items"], look["gender"], _emitter(on_event), judge=True)
