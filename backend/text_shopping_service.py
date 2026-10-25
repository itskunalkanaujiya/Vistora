"""
Text search: find products for a typed query with Google Shopping (SerpApi).

Returns the same sections as the photo search ("best_matches" and
"cheapest_alternatives") so the frontend can show both the same way.

Google Shopping returns loosely related listings (kurta sets for "kurti",
cases for a phone, the same item five times, imports at several times the
local price), so results are scored against the query before being shown.
"""

import os
import re
import statistics

import requests

from llm_query_parser import understand_query
from query_understanding import parse_query, requirements_score
from http_session import reliable_session
from search_credits import SearchLimitError, known_empty
from tryon_service import accessory_category, garment_category
from image_shopping_service import (
    QUERY_STOPWORDS,
    SERPAPI_URL,
    extract_price,
    format_price_text,
    get_domain,
    parse_numeric_price,
)

# A listing must reach this relevance score (0–1) to be shown.
MIN_RELEVANCE = 0.6
# If fewer listings than this pass, relax to this score so results aren't empty.
MIN_RESULTS_BEFORE_RELAXING = 6
RELAXED_RELEVANCE = 0.4

# Prices this many times the typical price go last in Top results. Lowest
# Prices only includes listings between LOW_PRICE_FACTOR (cheaper is likely an
# accessory or fake) and LOWEST_MAX_FACTOR times the typical price.
HIGH_PRICE_FACTOR = 3.0
LOW_PRICE_FACTOR = 0.25
LOWEST_MAX_FACTOR = 1.5

# Words that describe who a product is for; they matter least.
AUDIENCE_WORDS = {"men", "man", "women", "woman", "kid", "boy", "girl", "unisex",
                  "ladie", "lady", "gent", "baby", "adult", "children", "child"}

# Colours often go unmentioned in titles, so they matter less too.
COLOUR_WORDS = {"black", "white", "blue", "green", "red", "pink", "yellow", "grey",
                "gray", "brown", "purple", "orange", "maroon", "navy", "beige",
                "gold", "silver", "olive", "teal", "cream", "multicolour", "multicolor"}

# Words that mean the same product type, in normalised (singular) form.
SYNONYM_GROUPS = [
    {"earbud", "earphone", "airdope", "tws", "bud", "in-ear"},
    {"kurti", "kurta"},
    {"shoe", "sneaker", "trainer"},
    {"phone", "smartphone", "mobile"},
    {"laptop", "notebook"},
    {"tv", "television"},
    {"sofa", "couch"},
    {"tshirt", "tee"},
    {"fridge", "refrigerator"},
]
SYNONYMS = {word: group for group in SYNONYM_GROUPS for word in group}

# "<accessory> for <product>" means the listing is an accessory.
ACCESSORY_PATTERN = re.compile(
    r"\b(case|cover|strap|band|charger|cable|adapter|protector|guard|skin|"
    r"stand|holder|pouch|sleeve|replacement|refill|spare|tips?)\b"
    r"(?:\W+\w+){0,3}?\W+(for|compatible with)\b",
    re.IGNORECASE,
)
BUNDLE_PATTERN = re.compile(r"\b(set|combo|kit|pack of|bundle)\b", re.IGNORECASE)

USED_PATTERN = re.compile(r"\b(used|pre-?owned|second[- ]hand)\b", re.IGNORECASE)
REFURBISHED_PATTERN = re.compile(r"\b(refurbished|renewed|refurb|open[- ]box)\b", re.IGNORECASE)

# Cross-border resellers that list imported stock at several times the
# local price.
IMPORT_RESELLERS = {
    "desertcart", "ubuy", "kickscrew", "sportsupplyuk", "wafuu",
    "shoptheworld", "fruugo", "ebay",
}


def normalise_word(word):
    """Lower-case, singular form: "Women's" -> "women", "shoes" -> "shoe"."""
    word = word.lower().replace("’", "'")
    word = re.sub(r"'s$", "", word)
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def words_of(text, merge=True):
    text = (text or "").lower()
    # Brand names written several ways become one word:
    # "G-Shock", "G Shock" and "GShock" -> "gshock"; "T-shirt" -> "tshirt".
    if merge:
        text = re.sub(r"\b([b-hj-z])[\s-]+(?=[a-z]{2,})", r"\1", text)
    return [
        normalise_word(word)
        for word in re.findall(r"[a-z0-9’']+", text)
        if word not in QUERY_STOPWORDS
    ]


def query_terms(query):
    """
    Weighted query terms. The head noun (the product type, usually the last
    descriptive word, e.g. "kurti" in "cotton kurti for women") counts double;
    audience words ("men", "women") count half.
    """
    words = [word for word in words_of(query) if len(word) > 1]
    if not words:
        return {}, None

    descriptive = [
        word for word in words if word not in AUDIENCE_WORDS and word not in COLOUR_WORDS
    ]
    head = descriptive[-1] if descriptive else None

    weights = {}
    for word in words:
        if word == head:
            weights[word] = 2.0
        elif word in AUDIENCE_WORDS or word in COLOUR_WORDS:
            weights[word] = 0.5
        else:
            weights[word] = 1.0
    return weights, head


def model_words(query):
    """
    Words that identify a specific model or line and must appear in a
    listing: anything with a digit ("15", "ga2100") or a name written with a
    hyphen or a single letter ("g-shock" -> "gshock").
    """
    words = set(words_of(query))
    plain = set(words_of(query, merge=False))
    return {
        word
        for word in words
        if word not in AUDIENCE_WORDS
        and (any(char.isdigit() for char in word) or word not in plain)
    }


def title_matches(word, title_words):
    if word in title_words:
        return True
    return bool(SYNONYMS.get(word, set()) & title_words)


def relevance(title, query):
    """Score how well a listing title matches the query, from 0 to 1."""
    weights, head = query_terms(query)
    if not weights:
        return 1.0

    title_words = set(words_of(title))
    matched = sum(weight for word, weight in weights.items() if title_matches(word, title_words))
    score = matched / sum(weights.values())

    # The product type itself must match, unless the title names the brand
    # and line instead ("Casio G-Shock Mudmaster" for "casio g-shock watch"):
    # then every other main word must match.
    if head and not title_matches(head, title_words):
        main_words = [word for word, weight in weights.items() if weight == 1.0]
        if len(main_words) >= 2 and all(title_matches(w, title_words) for w in main_words):
            score = 0.75 * matched / (sum(weights.values()) - weights[head])
        else:
            score = min(score, 0.3)

    # A specific model or line in the query must be in the title.
    if any(not title_matches(word, title_words) for word in model_words(query)):
        score = min(score, 0.3)

    lowered_query = (query or "").lower()

    # An accessory for the product, when the query didn't ask for one.
    if ACCESSORY_PATTERN.search(title or "") and not ACCESSORY_PATTERN.search(lowered_query):
        score = min(score, 0.2)

    # A set or combo, when the query asked for a single item.
    if BUNDLE_PATTERN.search(title or "") and not BUNDLE_PATTERN.search(lowered_query):
        score *= 0.5

    return round(score, 4)


# Kept for compatibility with earlier callers.
def query_overlap(title, query):
    return relevance(title, query)


def item_condition(item):
    """"refurbished", "used" or None (new), from Google's field or the title."""
    reported = (item.get("second_hand_condition") or "").lower()
    title = item.get("title") or ""
    if "refurb" in reported or REFURBISHED_PATTERN.search(title):
        return "refurbished"
    if reported or USED_PATTERN.search(title):
        return "used"
    return None


def is_import_reseller(product):
    store = f"{product.get('marketplace', '')} {get_domain(product.get('product_url'))}".lower()
    return any(name in store for name in IMPORT_RESELLERS)


def title_key(title):
    """Identify the same product listed several times (case, sizes in brackets)."""
    title = re.sub(r"\([^)]*\)", " ", (title or "").lower())
    title = re.sub(r"\b(by myntra|at nykaa fashion.*)$", " ", title)
    return " ".join(re.findall(r"[a-z0-9]+", title))


# Reused connections skip a TLS handshake on every search.
_session = reliable_session()


def run_google_shopping(query: str) -> list[dict]:
    """Search Google Shopping in India and return the raw shopping results."""
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is missing from backend/.env")

    response = _session.get(
        SERPAPI_URL,
        params={
            "engine": "google_shopping",
            "q": query,
            "gl": "in",
            "hl": "en",
            "api_key": api_key,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    error = data.get("error")
    if error:
        # SerpApi reports an empty result as an error message.
        if "hasn't returned any results" in error:
            return []
        raise RuntimeError(error)

    results = data.get("shopping_results", [])
    return results if isinstance(results, list) else []


SERPER_SHOPPING_URL = "https://google.serper.dev/shopping"
SERPER_RESULTS = 40  # Serper charges 2 credits for 11-100 results


def run_serper_shopping(query: str) -> list[dict]:
    """
    Search Google Shopping in India through Serper.dev. Items are converted
    to SerpApi's field names so the rest of the pipeline is shared.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is missing from backend/.env")

    response = _session.post(
        SERPER_SHOPPING_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": "in", "hl": "en", "num": SERPER_RESULTS},
        timeout=8,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Serper returned {response.status_code}: {response.text[:200]}")

    items = response.json().get("shopping") or []
    return [from_serper(item) for item in items if isinstance(item, dict)]


def from_serper(item):
    """A Serper shopping item in SerpApi's shape."""
    return {
        "title": item.get("title"),
        "source": item.get("source"),
        "product_link": item.get("link"),
        "price": item.get("price"),
        "thumbnail": item.get("imageUrl"),
        "rating": item.get("rating"),
        "reviews": item.get("ratingCount"),
        "product_id": item.get("productId"),
    }


def fetch_shopping_results(query: str) -> tuple[list[dict], str]:
    """
    Google Shopping results and the provider used. Serper first: in our
    tests it was faster and more relevant for India, and its credits are
    separate from SerpApi's, which are kept for photo search. SerpApi is the
    fallback when Serper isn't set up, fails, runs out or finds nothing.
    """
    serper = bool(os.getenv("SERPER_API_KEY")) and not known_empty("serper")
    if serper:
        try:
            results = run_serper_shopping(query)
            if results:
                return results, "serper"
        except Exception as exc:
            print(f"Serper shopping failed, using SerpApi: {exc}")
    if known_empty("serpapi") and not serper:
        raise SearchLimitError()
    return run_google_shopping(query), "serpapi"


def build_shopping_product(item, query):
    """Convert a Google Shopping result into the frontend product format."""
    price_info = extract_price(item)
    if price_info["currency"] is None and price_info["price"] is not None:
        # gl=in returns rupee prices; label bare numbers as INR.
        price_info["currency"] = "INR"
        price_info["price_text"] = format_price_text(price_info["price"], "INR")

    original = parse_numeric_price(item.get("extracted_old_price"))
    if original is None:
        original = parse_numeric_price(item.get("old_price"))
    if original is not None and (price_info["price"] is None or original <= price_info["price"]):
        original = None

    url = item.get("link") or item.get("product_link")

    return {
        "pending": False,
        "result_type": "shopping",
        "name": item.get("title") or "Unknown product",
        "price": price_info["price"],
        "price_text": price_info["price_text"],
        "currency": price_info["currency"],
        "original_price": original,
        "original_price_text": (
            format_price_text(original, price_info["currency"] or "INR")
            if original is not None
            else None
        ),
        # Google Shopping does not report stock.
        "availability": "unknown",
        "marketplace": item.get("source") or get_domain(url) or "Online store",
        "multiple_sources": bool(item.get("multiple_sources")),
        "product_url": url,
        "image_url": item.get("thumbnail") or item.get("serpapi_thumbnail"),
        "source_icon": item.get("source_icon"),
        "tryon_category": garment_category(item.get("title")),
        "tryon_image_url": item.get("serpapi_thumbnail") or item.get("thumbnail"),
        "ar_category": accessory_category(item.get("title")),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "condition": item_condition(item),
        "visual_similarity_score": None,
        "text_relevance_score": relevance(item.get("title"), query),
        "match_type": "Google Shopping result",
    }


def search_products_by_text(
    query: str, max_results: int = 10, understand: bool = True, min_relevance: float | None = None
) -> dict:
    """
    Search Google Shopping for a typed query.

    Top results keep Google's order among relevant listings (imports and
    very high prices last); Lowest Prices are the cheapest remaining relevant
    listings, without suspiciously cheap ones.

    min_relevance replaces the usual title-match filter, for callers that
    rank the listings themselves (Find the outfit compares their photos).
    """
    if not 1 <= max_results <= 40:
        raise ValueError("max_results must be between 1 and 40.")

    query = (query or "").strip()
    if not query:
        raise ValueError("Search query cannot be empty.")

    # Read the request: "a laptop of 8gb ram with company hp" searches for
    # "hp laptop 8GB RAM" and ranks listings by how many requirements they meet.
    # understand=False reads the query with rules only (no language model),
    # for queries that are already clean searches.
    parsed = understand_query(query) if understand else parse_query(query)
    structured = parsed.is_structured
    search_query = parsed.search_query if structured else query
    match_query = parsed.core_query if structured else query

    results, provider = fetch_shopping_results(search_query)

    products = []
    seen_titles = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        product = build_shopping_product(item, match_query)
        product["requirements_score"] = (
            requirements_score(parsed, product["name"], product["marketplace"]) if structured else None
        )

        # Skip sponsored blocks and listings without a price or link.
        if product["price"] is None or not product["product_url"]:
            continue
        if product["currency"] != "INR":
            continue

        # The same product listed again (other sizes, sister stores).
        key = title_key(product["name"])
        if key in seen_titles:
            continue
        seen_titles.add(key)
        products.append(product)

    # A budget is a hard limit.
    if parsed.max_price is not None:
        products = [p for p in products if p["price"] <= parsed.max_price]
    if parsed.min_price is not None:
        products = [p for p in products if p["price"] >= parsed.min_price]

    relevant = [p for p in products if p["text_relevance_score"] >= (min_relevance or MIN_RELEVANCE)]
    if min_relevance is None and len(relevant) < MIN_RESULTS_BEFORE_RELAXING:
        relevant = [p for p in products if p["text_relevance_score"] >= RELAXED_RELEVANCE]
    if structured and len(relevant) < MIN_RESULTS_BEFORE_RELAXING:
        # Google already searched the precise request; titles often omit the
        # product word ("iQOO Z9 5G 8GB 128GB" for a phone). Trust its results,
        # still leaving out accessories the request didn't ask for.
        asked_accessory = ACCESSORY_PATTERN.search(search_query)
        relevant = [
            p for p in products
            if asked_accessory or not ACCESSORY_PATTERN.search(p["name"])
        ]

    if structured and (parsed.specs or parsed.features or parsed.brand):
        # Listings meeting none of the requirements are dropped while enough
        # others remain; the rest are ranked by requirements met, keeping
        # Google's order among equals.
        meeting = [p for p in relevant if p["requirements_score"]]
        if len(meeting) >= MIN_RESULTS_BEFORE_RELAXING:
            relevant = meeting
        relevant.sort(key=lambda p: (-(p["requirements_score"] or 0), p["condition"] is not None))

    typical_price = statistics.median(p["price"] for p in relevant) if relevant else None

    def sort_last(product):
        # Imports and prices far above typical go to the end; otherwise
        # Google's order is kept (sorted() is stable).
        too_high = typical_price and product["price"] > HIGH_PRICE_FACTOR * typical_price
        return bool(is_import_reseller(product) or too_high)

    ranked = sorted(relevant, key=sort_last)

    best_matches = ranked[:max_results]
    best_urls = {product["product_url"] for product in best_matches}

    cheapest_alternatives = sorted(
        (
            product
            for product in ranked
            if product["product_url"] not in best_urls
            and not is_import_reseller(product)
            and not (
                typical_price
                and not (
                    LOW_PRICE_FACTOR * typical_price
                    <= product["price"]
                    <= LOWEST_MAX_FACTOR * typical_price
                )
            )
        ),
        key=lambda product: product["price"],
    )[:max_results]

    print(
        f"Google Shopping: {len(results)} results, {len(products)} unique, "
        f"{len(relevant)} relevant for {search_query!r}."
    )

    return {
        "best_matches": best_matches,
        "cheapest_alternatives": cheapest_alternatives,
        "online_count": len(best_matches) + len(cheapest_alternatives),
        "online_search_query": query,
        "search_provider": provider,
        "search_query_used": search_query,
        # What the request was understood as, for the results page.
        "understood": parsed.summary() if structured else None,
    }
