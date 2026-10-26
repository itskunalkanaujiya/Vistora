import io
import json
import mimetypes
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import fast_photo
from http_session import reliable_session
from colour_match import colour_mismatch, photo_colours
from search_credits import SearchLimitError, known_empty
from tryon_service import accessory_category, garment_category, is_public_host

# CLIP ViT-B/32 image encoder run with ONNX Runtime (no PyTorch): it loads in a
# second or two, so a search never waits on a heavy start-up. Set
# ENABLE_CLIP_RANKING=false to rank by title and Google Lens order alone.
ENABLE_CLIP_RANKING = os.getenv("ENABLE_CLIP_RANKING", "true").lower() in {
    "true",
    "1",
    "yes",
    "on",
}

Image = None
np = None
onnxruntime = None
CLIP_AVAILABLE = False

try:
    from PIL import Image
except ImportError:
    pass

CLIP_ERROR = None

try:
    import numpy as np
    import onnxruntime

    CLIP_AVAILABLE = Image is not None
except Exception as exc:  # a missing wheel, or a native library that will not load
    CLIP_ERROR = f"{type(exc).__name__}: {exc}"
    print(f"CLIP unavailable ({CLIP_ERROR}); ranking by title and Lens order.")


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_IMAGE_URL = "https://serpapi.com/image"
# The CLIP ViT-B/32 image encoder, exported to ONNX with its weights stored in
# half precision (167 MB, split in two files to stay under GitHub's 100 MB limit)
# and computed in float32. Scores match the PyTorch model to 1e-6. Quantising to
# int8 shrank it to 84 MB but changed which listing looked nearest, so it is not used.
CLIP_MODEL_PARTS = [
    BASE_DIR / "models" / "clip_vision.onnx.part1",
    BASE_DIR / "models" / "clip_vision.onnx.part2",
]
CLIP_INPUT_SIZE = 224
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)

# Width of a title-match tie (see the sort in search_products_by_image). On 48 saved
# photos 0.5 ranked as well as exact scores did, and let Lens order the generic titles.
TITLE_BUCKET = 0.5
# Cheapest alternatives are ordered by price, so a barely related listing must not slip in.
ALTERNATIVE_MIN_RELEVANCE = 0.2
MIN_ALTERNATIVES = 3

# Turn off to skip thumbnail download and CLIP scoring in photo searches (saves
# ~2 s, but there are then no "looks N% similar" labels or cheaper look-alikes).
VISUAL_RERANK = os.getenv("VISUAL_RERANK", "true").lower() in {"1", "true", "yes", "on"}

MAX_IMAGE_BYTES = 512000
MAX_THUMBNAIL_BYTES = 3 * 1024 * 1024

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

PAGE_FETCH_TIMEOUT = 4
PAGE_FETCH_WORKERS = 16

# Seller pages still loading this many seconds after the Google Lens results
# arrive are skipped, however late they started.
PAGE_FETCH_DEADLINE = 5.0

THUMBNAIL_TIMEOUT = 5
THUMBNAIL_WORKERS = 16

# Thumbnails still downloading after this many seconds are not scored.
# Normally all arrive in about 2s; this only guards against a hung host.
THUMBNAIL_DEADLINE = 2.5

SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "CAD", "AUD", "JPY"}

NON_SHOPPING_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "thequint.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
}

# Words that appear in listing titles but say nothing about the product.
QUERY_STOPWORDS = {
    "a", "an", "and", "the", "for", "with", "of", "in", "on", "to", "by",
    "from", "at", "or", "is", "it", "its", "this", "that", "your", "you",
    "buy", "online", "shop", "shopping", "price", "prices", "best", "sale",
    "offer", "offers", "deal", "deals", "discount", "free", "shipping",
    "delivery", "new", "latest", "original", "genuine", "official", "store",
    "india", "indian", "inr", "rs", "usd", "com", "www", "pack", "pcs",
    "piece", "pieces", "set", "size", "sizes", "color", "colour", "colors",
    "colours", "variant", "item", "items", "product", "products", "review",
    "reviews", "specs", "specifications", "features", "amazon", "flipkart",
    "myntra", "ajio", "meesho", "snapdeal", "tatacliq", "croma", "nykaa",
    "jiomart", "shopsy", "ebay", "walmart", "etsy", "aliexpress", "alibaba",
}

QUERY_MAX_TITLES = 15
QUERY_MAX_WORDS = 6

# Marketplaces that sell in India but use a non-.in domain.
INDIAN_STORE_DOMAINS = {
    "flipkart.com",
    "myntra.com",
    "ajio.com",
    "meesho.com",
    "tatacliq.com",
    "nykaa.com",
    "nykaafashion.com",
    "croma.com",
    "jiomart.com",
    "snapdeal.com",
    "indiamart.com",
    "firstcry.com",
    "pepperfry.com",
    "lenskart.com",
    "bewakoof.com",
    "limeroad.com",
    "purplle.com",
    "bigbasket.com",
    "vijaysales.com",
    "urbanladder.com",
    "boat-lifestyle.com",
}

# Structured-data tags (JSON-LD, meta and itemprop links) that carry most
# stores' price and stock. Parsing only these is far cheaper than parsing
# the whole page, which otherwise slows down CLIP running alongside.
STRUCTURED_TAG_PATTERN = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>.*?</script>"
    r"|<meta\b[^>]*>"
    r"|<link\b[^>]*itemprop[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

# URL paths that identify a single product page.
PRODUCT_URL_PATTERN = re.compile(
    r"/(?:dp|gp/product|p|product|products|item|items|listing|proddetail|buy|pd)(?:/|$)"
    r"|/itm[0-9a-z]+|/p-mp[0-9a-z]+",
    re.IGNORECASE,
)

# URL paths and query strings for category, search, editorial or other
# pages that list or discuss products rather than sell one.
LISTING_URL_PATTERN = re.compile(
    r"/(?:search|s|category|categories|c|collections?|brands?|tags?|blogs?|news"
    r"|reviews?|forums?|wiki|pages)(?:/|$)|mega_menu|[?&](?:q|k|query|search)=",
    re.IGNORECASE,
)

# Titles that indicate a page about products rather than a product.
NON_PRODUCT_TITLE_PATTERN = re.compile(
    r"\b(?:review|reviews|unboxing|blog|menu|category|categories|catalogue|catalog|"
    r"launched|leak|leaked|leaks|hands-on|rumou?rs?|announced|how to|everything you need)\b",
    re.IGNORECASE,
)

# Accessories for a product (a screen guard for a watch, a cover for an e-reader)
# are not the product that was photographed. Only phrases that clearly mean an
# accessory are matched, so clothing ("full sleeve", "lace-up", "cable knit",
# "stand collar") is never dropped.
ACCESSORY_TITLE_PATTERN = re.compile(
    r"\bscreen ?(?:protectors?|guards?)\b"
    r"|\btempered glass\b"
    r"|\bprotectors?\b"
    r"|\bcompatible (?:with|for)\b"
    r"|\bskins\b"
    r"|\b(?:cover|case|skin|strap|band|stand|holder|cable|charger|sleeve|pouch|wrap|sticker|decal|"
    r"cushion|ear ?pad|ear ?tip|insole|lace)s?\b[^|,.;]{0,24}\bfor\b(?!\s+(?:men|women|kids?|boys?|girls?|ladies|unisex|him|her|babies|baby|adults?|youth|teens?)\b)",
    re.IGNORECASE,
)
# If the photo or the identified product is itself an accessory, none are dropped.
ACCESSORY_QUERY_WORDS = re.compile(
    r"\b(?:cover|covers|case|cases|strap|straps|band|bands|protector|protectors|guard|guards|charger|chargers|"
    r"cable|cables|stand|stands|holder|holders|skin|skins|sleeve|sleeves|pouch|pouches|sticker|stickers|"
    r"cushion|cushions|insole|insoles|lace|laces|tempered)\b",
    re.IGNORECASE,
)


def drop_accessories(items, query):
    """
    The listings without accessories for other products. Nothing is dropped when
    the photographed product is an accessory itself, or when that would leave
    nothing to show.
    """
    if ACCESSORY_QUERY_WORDS.search(query or ""):
        return items
    kept = [item for item in items if not ACCESSORY_TITLE_PATTERN.search(item.get("title") or "")]
    return kept or items

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "ref",
    "ref_",
}

_clip_model = None
_clip_processor = None
_clip_lock = threading.Lock()


# --------------------------------------------------
# Price parsing and currency helpers
# --------------------------------------------------


def parse_numeric_price(value):
    """Convert a supported price value into a numeric amount."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        price = float(value)
        if price >= 0 and price != float("inf") and price == price:
            return price
        return None

    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()

    # Avoid choosing an arbitrary endpoint of a price range.
    if re.search(
        r"\d\s*(?:-|–|—|\bto\b)\s*" r"(?:₹|Rs\.?|INR|USD|\$|€|£)?\s*\d",
        text,
        re.IGNORECASE,
    ):
        return None

    match = re.search(r"(?<!\d)\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None

    try:
        price = float(match.group(0).replace(",", ""))
    except ValueError:
        return None

    if price < 0 or price == float("inf") or price != price:
        return None

    return price


def detect_currency(value):
    if not isinstance(value, str):
        return None

    text = value.strip()
    upper_text = text.upper()

    for code in ("INR", "USD", "EUR", "GBP", "AED", "CAD", "AUD", "JPY"):
        if re.search(rf"\b{code}\b", upper_text):
            return code

    if "₹" in text or re.search(r"\bRs\.?\b", text, re.IGNORECASE):
        return "INR"
    if "€" in text:
        return "EUR"
    if "£" in text:
        return "GBP"
    if "¥" in text:
        return "JPY"
    if "$" in text:
        return "USD"

    return None


def normalize_currency(currency, price_text=None):
    if isinstance(currency, str):
        currency = currency.strip()

        symbol_map = {
            "₹": "INR",
            "Rs": "INR",
            "Rs.": "INR",
            "$": "USD",
            "€": "EUR",
            "£": "GBP",
            "¥": "JPY",
        }

        if currency in symbol_map:
            return symbol_map[currency]

        if currency.upper() in SUPPORTED_CURRENCIES:
            return currency.upper()

    return detect_currency(price_text)


def format_price_text(price, currency):
    if price is None:
        return None

    symbol_map = {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
    }

    amount = f"{price:,.2f}".rstrip("0").rstrip(".")
    symbol = symbol_map.get(currency)

    if symbol:
        return f"{symbol}{amount}"
    if currency:
        return f"{currency} {amount}"

    return None


def extract_price(item):
    """Extract price, display text, and currency from a SerpApi result."""
    raw_price = item.get("price")
    numeric_price = None
    price_text = None
    currency = None

    if isinstance(raw_price, dict):
        price_text = raw_price.get("value")
        currency = raw_price.get("currency")

        numeric_price = parse_numeric_price(raw_price.get("extracted_value"))
        if numeric_price is None:
            numeric_price = parse_numeric_price(price_text)

        if not currency:
            currency = detect_currency(price_text)

    elif raw_price is not None:
        numeric_price = parse_numeric_price(raw_price)

        if isinstance(raw_price, str):
            price_text = raw_price.strip() or None
            currency = detect_currency(raw_price)

    if numeric_price is None:
        numeric_price = parse_numeric_price(item.get("extracted_price"))

    currency = normalize_currency(currency, price_text)

    if numeric_price is not None and not price_text:
        price_text = format_price_text(numeric_price, currency)

    return {
        "price": numeric_price,
        "price_text": price_text,
        "currency": currency,
    }


# --------------------------------------------------
# URL and relevance helpers
# --------------------------------------------------


def get_domain(url):
    if not isinstance(url, str) or not url.strip():
        return ""

    try:
        hostname = (urlparse(url.strip()).hostname or "").lower()
        return hostname[4:] if hostname.startswith("www.") else hostname
    except ValueError:
        return ""


def normalize_product_url(url):
    if not isinstance(url, str) or not url.strip():
        return ""

    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        path = parsed.path.rstrip("/")
        query_params = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
        ]
        query_params.sort()

        return urlunparse(
            (
                parsed.scheme.lower() or "https",
                hostname,
                path,
                "",
                urlencode(query_params),
                "",
            )
        ).rstrip("/")

    except (ValueError, TypeError):
        return url.strip().lower()


def is_indian_store(url):
    """True when a listing URL belongs to a store that sells in India."""
    domain = get_domain(url)
    if not domain:
        return False

    if domain.endswith(".in"):
        return True

    if any(domain == d or domain.endswith("." + d) for d in INDIAN_STORE_DOMAINS):
        return True

    # International stores with an India section, e.g. /in/ or /en-in/.
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False

    return bool(re.match(r"^/(?:in|en-in|in-en|en_in|in_en)(?:/|$)", path))


def classify_listing_url(url):
    """Return "product", "listing" or None (unknown) for a listing URL."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None

    path = parsed.path or "/"
    target = path + ("?" + parsed.query if parsed.query else "")

    if PRODUCT_URL_PATTERN.search(path):
        return "product"

    if path.strip("/") == "" or LISTING_URL_PATTERN.search(target):
        return "listing"

    return None


def is_non_shopping_result(item):
    url = item.get("link") or ""
    domain = get_domain(url)

    if not domain:
        return True

    for blocked in NON_SHOPPING_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return True

    return not (item.get("title") or "").strip()


def product_relevance_score(item, query):
    title_words = set(re.findall(r"[a-z0-9]+", (item.get("title") or "").lower()))
    query_words = set(re.findall(r"[a-z0-9]+", query.lower()))

    if not query_words:
        return 0.0

    overlap = len(query_words & title_words) / len(query_words)
    source = (item.get("source") or "").lower()

    retail_terms = (
        "amazon",
        "flipkart",
        "myntra",
        "tatacliq",
        "croma",
        "reliance digital",
        "reliancedigital",
        "vijay sales",
    )

    retail_bonus = 0.15 if any(term in source for term in retail_terms) else 0.0
    price_bonus = 0.05 if extract_price(item)["price"] is not None else 0.0

    return overlap + retail_bonus + price_bonus


# --------------------------------------------------
# Dynamic product identification
# --------------------------------------------------


def title_keywords(item):
    """Return the meaningful words of a listing title, in title order."""
    title = (item.get("title") or "").lower()
    title = re.sub(r"['’]s\b", "", title)  # "men's" -> "men"

    # Keep hyphenated names together ("g-shock"), and join a lone letter
    # to the next word so "G Shock" also becomes "g-shock".
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", title)
    words = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        is_letter = len(token) == 1 and token.isalpha()

        if is_letter and token not in QUERY_STOPWORDS and index + 1 < len(tokens):
            token = f"{token}-{tokens[index + 1]}"
            index += 1

        index += 1

        if len(token) > 1 and token not in QUERY_STOPWORDS:
            words.append(token)

    return words


def derive_product_query(candidates):
    """
    Build a short search query from the words that Google Lens result
    titles agree on, e.g. "nike pegasus 41 running shoes".

    Higher-ranked results carry more weight. Returns "" if nothing useful
    can be derived.
    """
    titles = [
        words
        for words in (title_keywords(item) for item in candidates)
        if words
    ][:QUERY_MAX_TITLES]

    if not titles:
        return ""

    weights = {}
    positions = {}
    title_counts = {}
    total_weight = 0.0

    for rank, words in enumerate(titles):
        weight = 1.0 / (1.0 + 0.15 * rank)
        total_weight += weight

        for index, word in enumerate(dict.fromkeys(words)):
            weights[word] = weights.get(word, 0.0) + weight
            title_counts[word] = title_counts.get(word, 0) + 1
            positions.setdefault(word, []).append(index / max(len(words), 1))

    min_titles = 2 if len(titles) >= 2 else 1

    agreed = [
        word
        for word, weight in weights.items()
        if weight >= 0.3 * total_weight and title_counts[word] >= min_titles
    ]

    if not agreed:
        # No consensus: fall back to the top result's own title.
        return " ".join(titles[0][:QUERY_MAX_WORDS])

    # Keep the most agreed-on words, then restore natural title order.
    agreed.sort(key=lambda word: weights[word], reverse=True)
    agreed = agreed[:QUERY_MAX_WORDS]
    agreed.sort(key=lambda word: sum(positions[word]) / len(positions[word]))

    return " ".join(agreed)


# --------------------------------------------------
# CLIP visual similarity
# --------------------------------------------------


def preprocess_images(images):
    """
    CLIP's input: shortest side to 224 (bicubic), centre crop, normalise.
    Returns a float32 array of shape (n, 3, 224, 224).
    """
    size = CLIP_INPUT_SIZE
    batch = []
    for image in images:
        image = image.convert("RGB")
        width, height = image.size
        # Same rounding as the reference processor: the long side is truncated.
        if width <= height:
            new_size = (size, int(size * height / width))
        else:
            new_size = (int(size * width / height), size)
        image = image.resize(new_size, Image.BICUBIC)
        left, top = (image.width - size) // 2, (image.height - size) // 2
        image = image.crop((left, top, left + size, top + size))
        batch.append(np.asarray(image, dtype=np.float32) / 255.0)

    pixels = (np.stack(batch) - np.array(CLIP_MEAN, dtype=np.float32)) / np.array(
        CLIP_STD, dtype=np.float32
    )
    return pixels.transpose(0, 3, 1, 2).astype(np.float32)


def load_clip_model():
    """The ONNX session and the preprocessing function, loaded once; (None, None) if unavailable."""
    global _clip_model, _clip_processor

    if not ENABLE_CLIP_RANKING or not CLIP_AVAILABLE:
        return None, None

    with _clip_lock:
        if _clip_model is not None and _clip_processor is not None:
            return _clip_model, _clip_processor

        try:
            started = time.monotonic()
            weights = b"".join(part.read_bytes() for part in CLIP_MODEL_PARTS)
            _clip_model = onnxruntime.InferenceSession(
                weights, providers=["CPUExecutionProvider"]
            )
            _clip_processor = preprocess_images
            print(f"CLIP model loaded in {time.monotonic() - started:.1f}s.")
            return _clip_model, _clip_processor

        except Exception as exc:
            _clip_model = None
            _clip_processor = None
            CLIP_STATE["error"] = f"{type(exc).__name__}: {exc}"
            print(f"Could not load CLIP; using title ranking: {exc}")
            return None, None


CLIP_STATE = {"error": None}


def clip_state():
    """Whether CLIP is usable here, loading it if needed (for the status check)."""
    model, _ = load_clip_model()
    return {
        "enabled": ENABLE_CLIP_RANKING,
        "ready": model is not None,
        "error": CLIP_ERROR or CLIP_STATE["error"],
    }


# One connection pool for thumbnails: most come from the same few image
# hosts, and reusing connections skips a TLS handshake per thumbnail.
_thumbnail_session = requests.Session()
_thumbnail_session.mount(
    "https://", requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=THUMBNAIL_WORKERS)
)


def download_thumbnail(url, follow_redirects=True):
    if not isinstance(url, str) or not url.strip():
        return None

    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None

        with _thumbnail_session.get(
            url, headers=REQUEST_HEADERS, timeout=THUMBNAIL_TIMEOUT, stream=True,
            allow_redirects=follow_redirects,
        ) as response:
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not content_type.startswith("image/"):
                return None

            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    content.extend(chunk)
                    if len(content) > MAX_THUMBNAIL_BYTES:
                        return None

        if not content:
            return None

        with Image.open(io.BytesIO(content)) as image:
            image.load()
            return image.convert("RGB")

    except Exception as exc:
        print(f"Could not load product thumbnail: {exc}")
        return None


def download_thumbnails(candidates, deadline=THUMBNAIL_DEADLINE):
    """
    Download every candidate's thumbnail in parallel.

    Returns a list aligned with candidates (None where a download failed or
    missed the deadline).
    """
    pool = ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS)
    futures = [
        pool.submit(download_thumbnail, item.get("thumbnail")) for item in candidates
    ]
    wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)

    skipped = sum(1 for future in futures if not future.done())
    if skipped:
        print(f"Skipped {skipped} slow thumbnail(s).")

    return [
        future.result() if future.done() and not future.cancelled() else None
        for future in futures
    ]


def encode_images(model, processor, images):
    """Unit-length CLIP features, one row per image (a numpy array)."""
    features = model.run(None, {"pixel_values": processor(images)})[0]
    norms = np.linalg.norm(features, axis=-1, keepdims=True)
    return features / np.maximum(norms, 1e-12)


# Thumbnails are scored in groups of this size as they arrive.
CLIP_BATCH = 8


def open_query_image(image_path):
    if isinstance(image_path, Image.Image):
        return image_path.convert("RGB")

    with Image.open(image_path) as image:
        query_image = image.convert("RGB")
        query_image.load()
        return query_image


MAX_LIKE_CANDIDATES = 40


def public_image_url(url):
    """True for an http(s) link to a public host (never an internal address)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        isinstance(url, str)
        and parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and is_public_host(parsed.hostname)
    )


def similarity_to_reference(reference_url, urls):
    """
    How much each listing photo looks like the reference listing's photo:
    {url: cosine similarity}. Costs no search credit. The links come from the
    caller, so only public hosts are fetched, without following redirects.
    """
    model, processor = load_clip_model()
    if model is None or not public_image_url(reference_url):
        return {}

    unique = list(dict.fromkeys(u for u in urls[:MAX_LIKE_CANDIDATES] if public_image_url(u)))
    links = [reference_url] + [u for u in unique if u != reference_url]
    with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as pool:
        images = list(pool.map(lambda link: download_thumbnail(link, follow_redirects=False), links))

    if images[0] is None:
        return {}
    loaded = [(link, image) for link, image in zip(links, images) if image is not None]
    features = encode_images(model, processor, [image for _, image in loaded])
    similarities = features[1:] @ features[0]
    return {link: round(float(score), 4) for (link, _), score in zip(loaded[1:], similarities.tolist())}


def photo_colour_names(image_path):
    """The photo's main colours, or an empty set when it cannot be read."""
    try:
        return photo_colours(open_query_image(image_path))
    except Exception as exc:
        print(f"Could not read the photo's colours: {exc}")
        return set()


def download_and_score(image_path, candidates, deadline=THUMBNAIL_DEADLINE, on_downloaded=None):
    """
    Download every candidate's thumbnail and score it against the photo with
    CLIP, scoring groups of thumbnails while the rest are still downloading
    instead of waiting for all of them first.

    Returns (thumbnails, scores): thumbnails aligned with candidates (None
    where a download failed or missed the deadline) and CLIP similarities by
    candidate index (empty when CLIP is unavailable). on_downloaded() is
    called once the downloads are over, before the last group is scored.
    """
    model, processor = load_clip_model()
    query_image = None

    if model is not None and processor is not None and Image is not None:
        try:
            query_image = open_query_image(image_path)
        except Exception as exc:
            print(f"Could not open uploaded image for CLIP: {exc}")

    if query_image is None:
        thumbnails = download_thumbnails(candidates, deadline)
        if on_downloaded:
            on_downloaded()
        return thumbnails, {}

    thumbnails = [None] * len(candidates)
    scores = {}
    waiting = []  # (index, image) downloaded but not yet scored
    query_features = None

    def score_waiting():
        if not waiting or query_features is None:
            return
        features = encode_images(model, processor, [image for _, image in waiting])
        similarities = (features @ query_features).tolist()
        for (index, _), score in zip(waiting, similarities):
            scores[index] = round(float(score), 4)
        waiting.clear()

    stop = time.monotonic() + deadline
    pool = ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS)
    futures = {
        pool.submit(download_thumbnail, item.get("thumbnail")): index
        for index, item in enumerate(candidates)
    }
    pending = set(futures)

    try:
        # The photo's own features are ready before the first thumbnail.
        query_features = encode_images(model, processor, [query_image])[0]

        while pending:
            remaining = stop - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            for future in done:
                image = future.result()
                if image is not None:
                    thumbnails[futures[future]] = image
                    waiting.append((futures[future], image))
            if len(waiting) >= CLIP_BATCH:
                score_waiting()
    except Exception as exc:
        print(f"CLIP scoring failed; using text ranking: {exc}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if pending:
        print(f"Skipped {len(pending)} slow thumbnail(s).")

    if on_downloaded:
        on_downloaded()

    try:
        score_waiting()
    except Exception as exc:
        print(f"CLIP scoring failed; using text ranking: {exc}")

    return thumbnails, scores


def compute_visual_similarity_scores(image_path, candidates, thumbnails=None):
    """
    Return CLIP cosine similarities, not probabilities.

    image_path may also be a PIL image (e.g. a crop of the photo).

    Pass thumbnails from download_thumbnails() to reuse them; otherwise
    they are downloaded here.
    """
    if not candidates:
        return {}

    model, processor = load_clip_model()
    if model is None or processor is None or Image is None:
        return {}

    try:
        if isinstance(image_path, Image.Image):
            query_image = image_path.convert("RGB")
        else:
            with Image.open(image_path) as image:
                query_image = image.convert("RGB")
                query_image.load()
    except Exception as exc:
        print(f"Could not open uploaded image for CLIP: {exc}")
        return {}

    if thumbnails is None:
        thumbnails = download_thumbnails(candidates)

    valid_indices = []
    images = [query_image]

    for index, thumbnail in enumerate(thumbnails):
        if thumbnail is not None:
            valid_indices.append(index)
            images.append(thumbnail)

    if not valid_indices:
        return {}

    try:
        features = encode_images(model, processor, images)

        similarities = features[1:] @ features[0]

        return {
            index: round(float(score), 4)
            for index, score in zip(valid_indices, similarities.tolist())
        }

    except Exception as exc:
        print(f"CLIP scoring failed; using text ranking: {exc}")
        return {}


# --------------------------------------------------
# Stock availability helpers
# --------------------------------------------------

IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
UNKNOWN_AVAILABILITY = "unknown"


def classify_availability(value):
    """Map a stock value (schema.org URL, flag, or page text) to a status."""
    if isinstance(value, bool):
        return IN_STOCK if value else OUT_OF_STOCK

    if not isinstance(value, str) or not value.strip():
        return None

    text = re.sub(r"https?://schema\.org/", "", value.strip().lower())
    compact = re.sub(r"[\s_-]+", "", text)

    # Check "out of stock" first: "unavailable" contains "available".
    if compact in {"oos", "outofstock", "soldout", "discontinued"} or re.search(
        r"out of stock|sold out|currently unavailable|not available|unavailable",
        text,
    ):
        return OUT_OF_STOCK

    if compact in {
        "instock",
        "limitedavailability",
        "onlineonly",
        "instoreonly",
        "available",
    } or re.search(r"\bin stock\b|only \d+ left", text):
        return IN_STOCK

    return None


def serpapi_availability(item):
    """Read stock status from a Google Lens result, if it has one."""
    for key in ("in_stock", "availability", "stock_information", "stock"):
        status = classify_availability(item.get(key))
        if status:
            return status

    return None


# --------------------------------------------------
# Read price and availability from seller product pages
# --------------------------------------------------


def iter_jsonld_objects(soup):
    """Yield every JSON-LD object on the page, including nested offers."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        objects = [data]

        while objects:
            item = objects.pop(0)

            if isinstance(item, list):
                objects.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")
            if graph is not None:
                objects.append(graph)

            yield item

            offers = item.get("offers")
            if offers is not None:
                # AggregateOffer nests further offers, so walk them too.
                objects.append(offers)


def jsonld_types(item):
    value = item.get("@type")
    return set(value) if isinstance(value, list) else {value}


def has_product_markup(soup, jsonld):
    """True when the page declares itself a product (JSON-LD or Open Graph)."""
    if any("Product" in jsonld_types(item) for item in jsonld):
        return True

    og_type = soup.find("meta", attrs={"property": "og:type"})
    return bool(og_type and "product" in (og_type.get("content") or "").lower())


def offer_price_value(offer):
    """Return the raw price value from a schema.org offer."""
    for key in ("price", "lowPrice"):
        if offer.get(key) not in (None, ""):
            return offer[key]

    spec = offer.get("priceSpecification")
    specs = spec if isinstance(spec, list) else [spec]

    for spec in specs:
        if isinstance(spec, dict) and spec.get("price") not in (None, ""):
            return spec["price"]

    return None


def make_price_result(value, currency=None):
    """Build a price result; returns None if the amount or currency is unknown."""
    price = parse_numeric_price(value)
    if price is None or price <= 0:
        return None

    currency = normalize_currency(currency)
    if currency is None:
        return None

    return {
        "price": price,
        "price_text": format_price_text(price, currency),
        "currency": currency,
    }


def find_page_price(soup, html, hostname, offers, default_currency):
    """
    Find a product price on a seller page; return None if unknown.

    default_currency applies when the page does not state one. It is INR for
    Indian stores and None otherwise, so foreign prices are never mislabelled.
    """

    # Prefer structured JSON-LD product offers.
    for offer in offers:
        result = make_price_result(
            offer_price_value(offer),
            offer.get("priceCurrency") or default_currency,
        )
        if result:
            return result

    if hostname.endswith("amazon.in") or hostname.startswith("amazon."):
        selectors = [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "span.a-price span.a-offscreen",
            "meta[property='product:price:amount']",
            "meta[itemprop='price']",
        ]
    elif hostname.endswith("flipkart.com"):
        selectors = [
            "div.Nx9bqj",
            "div._30jeq3",
            "div._16Jk6d",
            "meta[itemprop='price']",
            "meta[property='product:price:amount']",
        ]
    else:
        selectors = [
            "meta[property='product:price:amount']",
            "meta[property='og:price:amount']",
            "meta[itemprop='price']",
            "[itemprop='price']",
        ]

    for selector in selectors:
        for element in soup.select(selector):
            value = (
                element.get("content")
                or element.get("data-price")
                or element.get_text(" ", strip=True)
            )
            cleaned = str(value).strip()

            if re.search(r"\d\s*[-–—]\s*(?:₹\s*)?\d", cleaned):
                continue

            result = make_price_result(
                cleaned, detect_currency(cleaned) or default_currency
            )
            if result:
                return result

    patterns = [
        r'"(?:sellingPrice|priceAmount|currentPrice)"'
        r'\s*:\s*"?([\d,]+(?:\.\d{1,2})?)"?',
        r'"price"\s*:\s*\{\s*"amount"' r'\s*:\s*"?([\d,]+(?:\.\d{1,2})?)"?',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            result = make_price_result(match.group(1), default_currency)
            if result:
                return result

    return None


def find_page_availability(soup, hostname, offers):
    """Find a stock status on a seller page; return None if unknown."""

    # Prefer structured JSON-LD offers.
    for offer in offers:
        status = classify_availability(offer.get("availability"))
        if status:
            return status

    for selector in (
        "meta[property='product:availability']",
        "meta[property='og:availability']",
        "[itemprop='availability']",
    ):
        for element in soup.select(selector):
            status = classify_availability(
                element.get("content")
                or element.get("href")
                or element.get_text(" ", strip=True)
            )
            if status:
                return status

    # Marketplace-specific stock messages.
    if hostname.endswith("amazon.in") or hostname.startswith("amazon."):
        element = soup.select_one("#availability")
        if element:
            return classify_availability(element.get_text(" ", strip=True))

    elif hostname.endswith("flipkart.com"):
        text = soup.get_text(" ", strip=True).lower()
        if "sold out" in text or "currently unavailable" in text:
            return OUT_OF_STOCK

    return None


# The "was" price Indian stores print beside the selling price, e.g.
# "M.R.P.: ₹2,999" or "MRP ₹1,499" (fake-discount check on the results page).
MRP_PATTERN = re.compile(
    r"(?:\bM\.?\s?R\.?\s?P\.?|\bList\s+Price|Maximum\s+Retail\s+Price)"
    r"[^0-9\u20b9<]{0,40}(?:<[^>]{0,200}>\s*){0,4}"
    r"(?:\u20b9|&#8377;|&#x20b9;|Rs\.?|INR)\s*(?:<[^>]{0,200}>\s*){0,2}"
    r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
MAX_MRP_FACTOR = 10  # an "MRP" over 10x the price is another product's


def find_mrp(html, price):
    """The page's MRP when it's above the selling price, else None."""
    if not html or not price:
        return None
    for match in MRP_PATTERN.finditer(html[:600000]):
        mrp = parse_numeric_price(match.group(1))
        if mrp and price < mrp <= MAX_MRP_FACTOR * price:
            return mrp
    return None


def fetch_page_details(url):
    """
    Fetch a seller page and read its price and stock status.

    Returns {"price", "price_text", "currency", "availability",
    "is_product_page", "fetched"}; values may be None when the page is
    blocked or does not expose them.
    """
    details = {
        "price": None,
        "price_text": None,
        "currency": None,
        "original_price": None,
        "availability": None,
        "is_product_page": None,
        "fetched": False,
    }

    if not url:
        return details

    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=PAGE_FETCH_TIMEOUT,
        )
        response.raise_for_status()
        html = response.text
    except requests.RequestException as exc:
        print(f"Could not fetch product page {url}: {exc}")
        return details

    details["fetched"] = True

    try:
        hostname = get_domain(url)
        is_marketplace = hostname.endswith("flipkart.com") or (
            hostname.endswith("amazon.in") or hostname.startswith("amazon.")
        )

        # Fast pass: read only the structured-data tags.
        fragment = "".join(STRUCTURED_TAG_PATTERN.findall(html))
        price_info, availability, is_product = read_page_details(
            BeautifulSoup(fragment, "html.parser"), fragment, url
        )

        # Full pass only when the fast pass missed the price, or for
        # Amazon/Flipkart, whose stock message is in the page body.
        if price_info is None or (availability is None and is_marketplace):
            price_info, availability, is_product = read_page_details(
                BeautifulSoup(html, "html.parser"), html, url
            )

        if price_info:
            details.update(price_info)
            details["original_price"] = find_mrp(html, price_info.get("price"))

        details["availability"] = availability
        details["is_product_page"] = is_product

    except Exception as exc:
        print(f"Could not read product page {url}: {exc}")

    return details


def read_page_details(soup, html, url):
    """Return (price_info, availability, is_product_page) for a parsed page."""
    hostname = get_domain(url)
    jsonld = list(iter_jsonld_objects(soup))
    offers = [
        item for item in jsonld if jsonld_types(item) & {"Offer", "AggregateOffer"}
    ]
    default_currency = "INR" if is_indian_store(url) else None

    price_info = find_page_price(soup, html, hostname, offers, default_currency)
    availability = find_page_availability(soup, hostname, offers)
    is_product = bool(offers or price_info or has_product_markup(soup, jsonld))

    return price_info, availability, is_product


def resolve_offer(item):
    """Combine Google Lens data with seller-page data for one listing."""
    price_info = extract_price(item)
    availability = serpapi_availability(item)
    page = item.get("_page_details") or {}

    if price_info["price"] is None and page.get("price") is not None:
        price_info = {
            "price": page["price"],
            "price_text": page["price_text"],
            "currency": page["currency"],
        }

    # Same store's price on Google Shopping, when the seller page gave none.
    if price_info["price"] is None and item.get("_shopping_price"):
        shopping = item["_shopping_price"]
        price_info = {
            "price": shopping["price"],
            "price_text": shopping["price_text"] or format_price_text(shopping["price"], "INR"),
            "currency": shopping["currency"],
        }

    if availability is None:
        availability = page.get("availability")

    # Indian stores sometimes list a bare number; treat it as rupees.
    if (
        price_info["price"] is not None
        and price_info["currency"] is None
        and is_indian_store(item.get("link"))
    ):
        price_info = {
            "price": price_info["price"],
            "price_text": format_price_text(price_info["price"], "INR"),
            "currency": "INR",
        }

    # The page's MRP, when it belongs to the price shown.
    original = page.get("original_price")
    if not (original and price_info["price"] and original > price_info["price"]
            and page.get("price") == price_info["price"]):
        original = None

    return {
        **price_info,
        "original_price": original,
        "availability": availability or UNKNOWN_AVAILABILITY,
    }


def looks_like_product_page(item):
    """Keep single-product listings; drop category, search and editorial pages."""
    if item["_offer"]["price"] is not None:
        return True

    if NON_PRODUCT_TITLE_PATTERN.search(item.get("title") or ""):
        return False

    page = item.get("_page_details") or {}
    if page.get("is_product_page"):
        return True

    kind = classify_listing_url(item.get("link"))
    if kind == "product":
        return True
    if kind == "listing":
        return False

    # Unknown URL with no price: keep it only if the page could not be
    # checked (blocked or too slow), giving it the benefit of the doubt.
    return not page.get("fetched")


def is_available_in_india(item):
    """Keep rupee-priced listings and Indian stores; drop foreign-currency ones."""
    offer = item["_offer"]

    if offer["price"] is not None and offer["currency"] == "INR":
        return True

    if offer["price"] is not None and offer["currency"] is not None:
        return False

    return is_indian_store(item.get("link"))


def probably_available_in_india(item):
    """is_available_in_india() using only Google Lens data (before seller pages)."""
    price = extract_price(item)
    if price["price"] is not None and price["currency"] is not None:
        return normalize_currency(price["currency"], price["price_text"]) == "INR"
    return is_indian_store(item.get("link"))


def needs_page_details(item):
    return bool(item.get("link")) and (
        extract_price(item)["price"] is None or serpapi_availability(item) is None
    )


def start_page_details(candidates, deadline=None):
    """
    Start fetching seller pages in the background for listings missing
    price or stock, so the fetches overlap with CLIP scoring.
    """
    pool = ThreadPoolExecutor(max_workers=PAGE_FETCH_WORKERS)
    futures = {
        pool.submit(fetch_page_details, item["link"]): item
        for item in candidates
        if needs_page_details(item)
    }
    if deadline is None:
        deadline = time.monotonic() + PAGE_FETCH_DEADLINE

    return pool, futures, deadline


def finish_page_details(job):
    """Collect the seller pages that finished before the deadline."""
    pool, futures, deadline = job

    done, not_done = wait(futures, timeout=max(0.0, deadline - time.monotonic()))

    for future in done:
        try:
            futures[future]["_page_details"] = future.result()
        except Exception as exc:
            print(f"Seller page fetch failed: {exc}")

    if not_done:
        print(f"Skipped {len(not_done)} slow seller page(s).")

    # Do not wait for the slow pages; their results are no longer needed.
    pool.shutdown(wait=False, cancel_futures=True)


# --------------------------------------------------
# Prices from Google Shopping (Serper.dev)
# --------------------------------------------------

# A Lens listing borrows a Google Shopping price only from the same store,
# when most of the shorter title's words appear in the other title.
SHOPPING_TITLE_OVERLAP = 0.6
STORE_SUFFIX_PATTERN = re.compile(r"(\.(com|in|co\.in|net|store))+$|^www\.")


def start_shopping_prices(query):
    """
    Look up the identified product on Google Shopping in the background, to
    fill prices Google Lens leaves out. Uses Serper.dev's own credits, so it
    costs no SerpApi search; returns None when Serper isn't set up.
    """
    if not query or not os.getenv("SERPER_API_KEY"):
        return None
    from text_shopping_service import run_serper_shopping  # avoids a circular import

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(run_serper_shopping, query)
    pool.shutdown(wait=False)
    return future


def store_key(name):
    """Comparable store name: "Amazon.in", "amazon.in" and "Amazon" match."""
    text = re.sub(r"\s+", "", (name or "").lower())
    return STORE_SUFFIX_PATTERN.sub("", text)


def title_words(title):
    return {word for word in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(word) > 2}


def apply_shopping_prices(candidates, job, deadline):
    """Fill missing prices from the background Google Shopping lookup."""
    if job is None:
        return 0
    try:
        shopping = job.result(timeout=max(0.5, deadline - time.monotonic()))
    except Exception as exc:
        print(f"Google Shopping price lookup failed: {exc}")
        return 0

    offers = []
    for entry in shopping:
        price = extract_price(entry)
        if price["price"] is not None and entry.get("source"):
            offers.append((store_key(entry["source"]), title_words(entry.get("title")), price))

    filled = 0
    for item in candidates:
        page = item.get("_page_details") or {}
        if extract_price(item)["price"] is not None or page.get("price") is not None:
            continue
        store = store_key(item.get("source"))
        words = title_words(item.get("title"))
        if not store or not words:
            continue

        best = None
        for offer_store, offer_words, price in offers:
            if offer_store != store or not offer_words:
                continue
            overlap = len(words & offer_words) / min(len(words), len(offer_words))
            if overlap >= SHOPPING_TITLE_OVERLAP and (best is None or overlap > best[0]):
                best = (overlap, price)
        if best:
            item["_shopping_price"] = {**best[1], "currency": best[1]["currency"] or "INR"}
            filled += 1
    return filled


# --------------------------------------------------
# Product building and two-section ranking
# --------------------------------------------------


def build_product(item, pending=False):
    """
    Convert a raw search result into the frontend product format.

    pending marks a preview listing whose seller page is still being checked,
    so its price or stock may still change.
    """
    offer = item["_offer"]
    visual_score = item.get("_visual_similarity_score")

    return {
        "pending": pending,
        "name": item.get("title") or "Unknown product",
        "price": offer["price"],
        "price_text": offer["price_text"],
        "currency": offer["currency"],
        "original_price": offer.get("original_price"),
        "original_price_text": (
            format_price_text(offer["original_price"], offer["currency"] or "INR")
            if offer.get("original_price")
            else None
        ),
        "availability": offer["availability"],
        "marketplace": item.get("source") or "Unknown seller",
        "product_url": item.get("link"),
        "image_url": item.get("thumbnail"),
        "source_icon": item.get("source_icon"),
        # Try-on works best with the full-size product photo.
        "tryon_category": garment_category(item.get("title")),
        "tryon_image_url": item.get("image") or item.get("thumbnail"),
        "ar_category": accessory_category(item.get("title")),
        "visual_similarity_score": visual_score,
        "text_relevance_score": round(item.get("_text_relevance_score", 0.0), 4),
        "match_type": (
            "CLIP-ranked visual candidate"
            if visual_score is not None
            else "Text-ranked visual candidate"
        ),
    }


# Dupe finder: listings that look like the closest matches (CLIP "Similar"
# or better) but cost much less than them.
DUPE_MIN_SIMILARITY = 0.78
DUPE_MAX_PRICE_SHARE = 0.7  # at most 70% of the closest matches' price
DUPE_REFERENCE_COUNT = 3  # closest priced matches that set the reference price
MAX_DUPES = 6


def find_dupes(kept):
    """
    Cheaper lookalikes among the kept listings: [(item, reference_price)],
    biggest saving first. The reference is the median price of the most
    visually similar priced listings (usually the original product).
    """
    priced = [
        item for item in kept
        if item["_offer"]["price"] is not None
        and item["_offer"]["currency"] == "INR"
        and item.get("_visual_similarity_score") is not None
    ]
    if len(priced) < DUPE_REFERENCE_COUNT + 1:
        return []

    by_similarity = sorted(priced, key=lambda item: -item["_visual_similarity_score"])
    reference_prices = sorted(item["_offer"]["price"] for item in by_similarity[:DUPE_REFERENCE_COUNT])
    reference = reference_prices[len(reference_prices) // 2]

    dupes = [
        item for item in by_similarity[DUPE_REFERENCE_COUNT:]
        if item["_visual_similarity_score"] >= DUPE_MIN_SIMILARITY
        and item["_offer"]["price"] <= reference * DUPE_MAX_PRICE_SHARE
        and item["_offer"]["availability"] != OUT_OF_STOCK
    ]
    dupes.sort(key=lambda item: item["_offer"]["price"])
    return [(item, reference) for item in dupes[:MAX_DUPES]]


def select_sections(candidates, max_results, preview=False, query=""):
    """
    Resolve offers, filter, and pick the Best Matches and Cheapest
    Alternatives sections from candidates already ranked by similarity.

    In a preview, seller pages have not been read yet: listings that still
    need them are marked pending.
    """
    for item in candidates:
        item["_offer"] = resolve_offer(item)

    # Drop non-product pages and listings that cannot be bought in rupees.
    kept = [
        item
        for item in candidates
        if looks_like_product_page(item) and is_available_in_india(item)
    ]
    kept = drop_accessories(kept, query)

    def product(item):
        return build_product(item, pending=preview and needs_page_details(item))

    # Best Matches: prioritize visual similarity and title relevance.
    best_items = kept[:max_results]

    # Cheapest Alternatives: only products with known prices can be sorted
    # reliably. Out-of-stock listings go last, and listings already shown
    # in Best Matches are not repeated.
    best_urls = {normalize_product_url(item.get("link")) for item in best_items}

    alternative_items = [
        item
        for item in kept
        if item["_offer"]["price"] is not None
        and normalize_product_url(item.get("link")) not in best_urls
    ]

    relevant = [
        item for item in alternative_items
        if item.get("_text_relevance_score", 1.0) >= ALTERNATIVE_MIN_RELEVANCE
    ]
    if len(relevant) >= MIN_ALTERNATIVES:
        alternative_items = relevant

    alternative_items.sort(
        key=lambda item: (
            item["_offer"]["availability"] == OUT_OF_STOCK,
            item["_offer"]["price"],
        )
    )

    dupes = []
    if not preview:
        for item, reference in find_dupes(kept):
            dupe = product(item)
            dupe["dupe_reference_price"] = reference
            dupe["dupe_savings"] = round(reference - item["_offer"]["price"], 2)
            dupes.append(dupe)

    return {
        "best_matches": [product(item) for item in best_items],
        "cheapest_alternatives": [
            product(item) for item in alternative_items[:max_results]
        ],
        "dupes": dupes,
        "filtered_count": len(candidates) - len(kept),
    }


# --------------------------------------------------
# Fast Google Lens: SearchApi.io with the photo on Vercel Blob
# --------------------------------------------------

# SearchApi's Google Lens answered in 5-9 s where SerpApi took 9-41 s in our
# tests, with the same matches. It only reads images from a public link, so
# the photo is put on Vercel Blob under an unguessable name for the few
# seconds the search takes, then deleted.
SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"
BLOB_API_URL = "https://blob.vercel-storage.com"
BLOB_API_VERSION = "11"


# Reused connections skip a TLS handshake on every Blob / Lens call.
_api_session = reliable_session()


def fast_lens_available():
    """The fast provider is set up AND switched on (it is off by default; see fast_photo.py)."""
    return bool(
        os.getenv("SEARCHAPI_API_KEY") and os.getenv("BLOB_READ_WRITE_TOKEN") and fast_photo.enabled()
    )


def _blob_headers():
    return {
        "authorization": f"Bearer {os.environ['BLOB_READ_WRITE_TOKEN']}",
        "x-api-version": BLOB_API_VERSION,
    }


def upload_temporary_image(image_path, mime_type):
    """Put the photo on Vercel Blob and return its public URL."""
    extension = {"image/png": "png", "image/webp": "webp"}.get(mime_type, "jpg")
    response = _api_session.put(
        f"{BLOB_API_URL}/?pathname=lens/photo.{extension}",
        data=Path(image_path).read_bytes(),
        headers={
            **_blob_headers(),
            "x-content-type": mime_type,
            "x-add-random-suffix": "1",
            "x-cache-control-max-age": "60",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["url"]


def delete_temporary_image(url):
    try:
        requests.post(f"{BLOB_API_URL}/delete", json={"urls": [url]}, headers=_blob_headers(), timeout=20)
    except Exception as exc:
        print(f"Could not delete temporary image: {exc}")


def from_searchapi(item):
    """A SearchApi visual match in SerpApi's shape."""
    converted = dict(item)
    image = item.get("image")
    converted["image"] = image.get("link") if isinstance(image, dict) else image
    if item.get("price") and item.get("extracted_price") is not None:
        converted["price"] = {
            "value": item["price"],
            "extracted_value": item["extracted_price"],
            "currency": item.get("currency"),
        }
    return converted


def run_searchapi_lens(image_path, mime_type, query=None):
    """Google Lens through SearchApi.io; raw visual matches in SerpApi's shape."""
    started = time.monotonic()
    url = upload_temporary_image(image_path, mime_type)
    uploaded = time.monotonic()
    try:
        params = {
            "engine": "google_lens",
            "url": url,
            "country": "in",
            "hl": "en",
            "api_key": os.environ["SEARCHAPI_API_KEY"],
        }
        if query:
            params["q"] = query
        response = _api_session.get(SEARCHAPI_URL, params=params, timeout=25)
        data = response.json()
        if response.status_code != 200 or data.get("error"):
            raise RuntimeError(f"{response.status_code}: {str(data.get('error') or data)[:200]}")
    finally:
        # SearchApi has read the photo by now; remove it in the background.
        threading.Thread(target=delete_temporary_image, args=(url,), daemon=True).start()

    matches = [from_searchapi(item) for item in data.get("visual_matches") or [] if isinstance(item, dict)]
    print(
        f"Lens timings (SearchApi): upload {uploaded - started:.1f}s, "
        f"search {time.monotonic() - uploaded:.1f}s, {len(matches)} matches"
    )
    return matches


def run_google_lens(image_path: str | Path, query: str | None = None) -> list[dict]:
    """
    Upload an image to SerpApi and return Google Lens shopping candidates,
    filtered and deduplicated, in Lens's own ranking order.

    Without a query, Lens identifies the product by itself. A query (for
    example a brand and model the user typed) narrows the visual search.
    """

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is missing from backend/.env")

    image_path = Path(image_path)

    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    if image_path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image must be no larger than 500 KB.")

    mime_type = mimetypes.guess_type(image_path.name)[0]
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Use a JPEG, PNG, or WebP image.")

    visual_matches = None
    # A provider that was just read as out of credits is skipped: its call
    # would fail anyway, after seconds of waiting.
    fast = fast_lens_available() and not known_empty("searchapi")
    if fast:
        try:
            visual_matches = run_searchapi_lens(image_path, mime_type, query)
        except Exception as exc:
            print(f"Fast Lens (SearchApi) failed, using SerpApi: {exc}")
    if not visual_matches:
        if known_empty("serpapi") and not fast:
            raise SearchLimitError()
        visual_matches = run_serpapi_lens(image_path, mime_type, api_key, query)

    return shopping_candidates(visual_matches)


def run_serpapi_lens(image_path, mime_type, api_key, query=None):
    """Upload the image to SerpApi and return Google Lens's raw visual matches."""
    # Upload image to SerpApi.
    upload_started = time.monotonic()
    with image_path.open("rb") as image_file:
        upload_response = requests.post(
            SERPAPI_IMAGE_URL,
            data={"api_key": api_key},
            files={"image": (image_path.name, image_file, mime_type)},
            timeout=30,
        )

    upload_response.raise_for_status()
    upload_data = upload_response.json()

    if upload_data.get("error"):
        raise RuntimeError(upload_data["error"])

    image_id = upload_data.get("image_id")
    if not image_id:
        raise RuntimeError("Image upload returned no image_id.")

    # Search Google Lens.
    search_started = time.monotonic()
    visual_matches = fetch_visual_matches(api_key, image_id, query=query)
    print(
        f"Lens timings: upload {search_started - upload_started:.1f}s "
        f"({image_path.stat().st_size // 1024} KB), search {time.monotonic() - search_started:.1f}s"
    )

    # Google Lens occasionally returns an empty response; retry once
    # without SerpApi's cache before giving up.
    if not visual_matches:
        print("Google Lens returned no visual matches; retrying once.")
        visual_matches = fetch_visual_matches(
            api_key, image_id, no_cache=True, query=query
        )

    return visual_matches


def shopping_candidates(visual_matches):
    """Shopping listings from raw visual matches, filtered and deduplicated."""
    # Filter and deduplicate before scoring. The same listing can appear
    # under several URLs, so also match on title and seller.
    candidates = []
    seen_urls = set()
    seen_listings = set()

    for item in visual_matches:
        if not isinstance(item, dict) or is_non_shopping_result(item):
            continue

        product_url = item.get("link")
        normalized_url = normalize_product_url(product_url)
        listing_key = (
            (item.get("title") or "").strip().lower(),
            get_domain(product_url),
        )

        if (
            not normalized_url
            or normalized_url in seen_urls
            or listing_key in seen_listings
        ):
            continue

        seen_urls.add(normalized_url)
        seen_listings.add(listing_key)
        candidates.append(item)

    print(
        f"Google Lens: {len(visual_matches)} visual matches, "
        f"{len(candidates)} shopping candidates kept."
    )

    return candidates


def fetch_visual_matches(api_key, image_id, no_cache=False, query=None):
    """Run one Google Lens search and return its raw visual matches."""
    params = {
        "engine": "google_lens",
        "image_id": image_id,
        "country": "in",
        "hl": "en",
        "api_key": api_key,
    }

    if query:
        params["q"] = query

    if no_cache:
        params["no_cache"] = "true"

    search_response = _api_session.get(SERPAPI_URL, params=params, timeout=40)
    search_response.raise_for_status()
    data = search_response.json()

    error = data.get("error")
    if error:
        # SerpApi reports an empty Lens result as an error message.
        if "hasn't returned any results" in error:
            print(f"Google Lens: {error}")
            return []
        raise RuntimeError(error)

    visual_matches = data.get("visual_matches", [])

    if not isinstance(visual_matches, list) or not visual_matches:
        print(f"Google Lens response had no visual matches; keys: {list(data)}")
        return []

    return visual_matches


def identify_product(image_path: str | Path) -> dict:
    """Identify the product in an image using Google Lens results."""
    candidates = run_google_lens(image_path)

    return {
        "query": derive_product_query(candidates),
        "top_titles": [item.get("title") for item in candidates[:5]],
    }


def search_products_by_image(
    image_path: str | Path,
    max_results: int = 10,
    on_event=None,
    query: str | None = None,
) -> dict:
    """
    Search Google Lens and return two separate sections.

    on_event(event_type, payload), if given, is called as the search
    progresses so results can be shown early:
        "identified" {"online_search_query"}            after Google Lens
        "preview"    {"best_matches", "cheapest_alternatives",
                      "online_search_query"}             after CLIP ranking,
                                                         before seller pages

    Returns:
        {
            "best_matches": [...],
            "cheapest_alternatives": [...],
            "online_count": int,
            "online_search_query": str
        }

    online_search_query is derived from the Lens results unless a query is
    given, in which case Lens is searched with it and it is used as-is.
    max_results is the maximum number of items in EACH section.
    """

    if not 1 <= max_results <= 40:
        raise ValueError("max_results must be between 1 and 40.")

    started = time.monotonic()

    def emit(event_type, payload):
        if on_event is not None:
            try:
                on_event(event_type, payload)
            except Exception as exc:
                print(f"Search event handler failed: {exc}")

    candidates = run_google_lens(image_path, query=query)
    query = query or derive_product_query(candidates)
    lens_done = time.monotonic()

    emit("identified", {"online_search_query": query})
    shopping_job = start_shopping_prices(query) if candidates else None

    if not candidates:
        return {
            "best_matches": [],
            "cheapest_alternatives": [],
            "online_count": 0,
            "online_search_query": query,
        }

    for item in candidates:
        item["_text_relevance_score"] = product_relevance_score(item, query)

    # Keep a larger pool so cheaper products have a chance to appear.
    # This avoids selecting only the first max_results candidates.
    # Google Lens already ranks candidates using the uploaded image.
    # Keep its initial ordering instead of filtering by title relevance first.
    # CLIP will perform the visual re-ranking on this larger candidate pool.
    candidate_limit = max(max_results * 2, 20, 24)

    # Drop listings that will be filtered out anyway (foreign currency, or
    # no price and not an Indian store) before choosing the pool, so the
    # pool is all usable listings.
    usable = [item for item in candidates if probably_available_in_india(item)]
    candidates = (usable or candidates)[:candidate_limit]

    # Show Lens's own order and prices straight away; CLIP re-ranks after.
    if on_event is not None:
        early = select_sections(candidates, max_results, preview=True, query=query)
        emit(
            "preview",
            {
                "best_matches": early["best_matches"],
                "cheapest_alternatives": early["cheapest_alternatives"],
                "online_search_query": query,
                "ranked": False,
            },
        )

    # CLIP reorders the larger pool by visual similarity, scoring thumbnails
    # as they download. Seller-page fetching waits until the downloads are
    # over: it competes for the CPU and would slow them enough to miss some,
    # then loads in the background while the last group is scored.
    page_jobs = []

    def start_pages():
        page_jobs.append(
            start_page_details(candidates, deadline=lens_done + PAGE_FETCH_DEADLINE)
        )

    if VISUAL_RERANK:
        thumbnails, similarity_scores = download_and_score(
            image_path, candidates, on_downloaded=start_pages
        )
    else:
        # Visual scoring costs ~3 s per search and, measured on 48 photos, does
        # not improve which product comes first, so seller pages start at once.
        similarity_scores = {}
    page_job = page_jobs[0] if page_jobs else start_page_details(
        candidates, deadline=lens_done + PAGE_FETCH_DEADLINE
    )
    clip_done = time.monotonic()

    for index, item in enumerate(candidates):
        item["_visual_similarity_score"] = similarity_scores.get(index)

    # Title match first: the listings that name the identified product come first,
    # and visual similarity only settles ties. Ordering by looks alone put
    # look-alikes (a Flip 3 for a Flip 4, a case for what it covers) above the
    # exact model; in a test on 33 photos, the exact product went from first for
    # 61% of photos to 94%. Visual similarity still drives the "cheaper
    # lookalikes" and the "looks N% similar" labels.
    # Titles are coarse (generic words like "kids frock" match a green frock as
    # well as the orange one in the photo), so listings within TITLE_BUCKET of
    # each other count as tied and keep Google Lens's own order, which is its
    # visual match. A stable sort keeps that order among ties.
    # A listing whose title names only colours that are not in the photo (a
    # green frock for an orange one) goes below equally good ones.
    photo_palette = photo_colour_names(image_path)
    for item in candidates:
        item["_colour_mismatch"] = colour_mismatch(item.get("title"), photo_palette)

    candidates.sort(
        key=lambda item: (
            round(item["_text_relevance_score"] / TITLE_BUCKET),
            not item["_colour_mismatch"],
            item["_visual_similarity_score"] or 0,
        ),
        reverse=True,
    )

    # Show ranked results with Google Lens prices while seller pages load.
    if on_event is not None:
        preview = select_sections(candidates, max_results, preview=True, query=query)
        emit(
            "preview",
            {
                "best_matches": preview["best_matches"],
                "cheapest_alternatives": preview["cheapest_alternatives"],
                "online_search_query": query,
                "ranked": True,
            },
        )

    # Read price and stock from seller pages where Lens lacks them, then
    # fill what's still missing from Google Shopping.
    finish_page_details(page_job)
    filled = apply_shopping_prices(candidates, shopping_job, lens_done + PAGE_FETCH_DEADLINE)
    if filled:
        print(f"Filled {filled} price(s) from Google Shopping.")
    pages_done = time.monotonic()

    print(
        f"Search timings: lens {lens_done - started:.1f}s, "
        f"thumbnails+clip {clip_done - lens_done:.1f}s, "
        f"pages +{pages_done - clip_done:.1f}s, "
        f"total {pages_done - started:.1f}s "
        f"({len(candidates)} candidates)"
    )

    sections = select_sections(candidates, max_results, query=query)
    print(f"Filtered {sections['filtered_count']} non-product or foreign listing(s).")

    best_matches = sections["best_matches"]
    cheapest_alternatives = sections["cheapest_alternatives"]

    return {
        "best_matches": best_matches,
        "cheapest_alternatives": cheapest_alternatives,
        "dupes": sections["dupes"],
        "online_count": len(best_matches) + len(cheapest_alternatives),
        "online_search_query": query,
    }
