from collections import OrderedDict, deque
from contextlib import asynccontextmanager, contextmanager
from io import BytesIO
from pathlib import Path
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time

import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from image_shopping_service import (
    identify_product,
    load_clip_model,
    search_products_by_image as search_online_products,
)
import fast_photo
import search_credits
import shared_cache
from popular_searches import POPULAR_SEARCHES
from text_shopping_service import search_products_by_text as search_shopping_text
from outfit_service import OutfitError, complete_the_look, find_outfit
from style_service import analyse_colours, rate_outfit
from assistant_service import AssistantError, ask_assistant, compare_products
from room_service import find_room
from planner_service import PlanError, plan_look, read_budget
from gift_service import find_gifts
from list_service import shop_list
from price_watch_service import PriceWatchError, check_prices
from tryon_service import GARMENT_WORDS, TryOnError, product_overlay, try_on

# --------------------------------------------------
# 1. Create the FastAPI application
# --------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load CLIP in the background so the first search does not wait for it,
    # while the server still starts accepting requests immediately.
    threading.Thread(target=load_clip_model, daemon=True).start()
    yield


app = FastAPI(
    title="Vistora",
    version="0.4.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# 2. Allow requests from the React frontend
# --------------------------------------------------

# Local development is always allowed. In production, list the frontend's
# address in ALLOWED_ORIGINS (comma-separated), and optionally allow Vercel
# preview deployments with ALLOWED_ORIGIN_REGEX, for example
#   https://(snapbuy-ai|vistora)(-[a-z0-9-]+)?\.vercel\.app
LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

allowed_origins = LOCAL_ORIGINS + [
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=os.getenv("ALLOWED_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Lens-Centres"],
)


# --------------------------------------------------
# 3. Image upload settings
# --------------------------------------------------

MAX_FILE_SIZE = 8 * 1024 * 1024  # 8 MB
MAX_IMAGE_PIXELS = 20_000_000

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

ALLOWED_IMAGE_FORMATS = {
    "JPEG",
    "PNG",
    "WEBP",
}


# --------------------------------------------------
# 4. Validate and open an uploaded image
# --------------------------------------------------


async def read_uploaded_image(file: UploadFile) -> Image.Image:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Upload a JPEG, PNG, or WebP image.",
        )

    contents = await file.read(MAX_FILE_SIZE + 1)

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Image size must not exceed 8 MB.",
        )

    try:
        # Verify that the uploaded bytes form a valid image.
        with Image.open(BytesIO(contents)) as check_image:
            if check_image.format not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(
                    status_code=415,
                    detail="Unsupported image format.",
                )

            if check_image.width * check_image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=413,
                    detail="Image dimensions are too large.",
                )

            check_image.verify()

        # Reopen because verify() invalidates normal image access.
        with Image.open(BytesIO(contents)) as image:
            image.load()
            return image.convert("RGB")

    except HTTPException:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid image.",
        )


# --------------------------------------------------
# 5. Prepare the image for Google Lens
# --------------------------------------------------

LENS_MAX_BYTES = 500_000

ONLINE_SEARCH_ERROR = (
    "Online search failed. Check the backend terminal for details, "
    "and verify your SerpApi API key, quota, and internet connection."
)


def search_failure(exc):
    """The HTTP error for a failed search: a clear message when every provider is out of credits."""
    if isinstance(exc, search_credits.SearchLimitError):
        return HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "3600"})
    return HTTPException(status_code=502, detail=ONLINE_SEARCH_ERROR)


@contextmanager
def lens_ready_image(image: Image.Image):
    """Yield a temporary JPEG small enough for the online service."""
    with tempfile.NamedTemporaryFile(
        suffix=".jpg",
        delete=False,
    ) as temp_file:
        temp_image_path = Path(temp_file.name)

    try:
        online_image = image.copy()
        online_image.thumbnail((1000, 1000))

        quality = 85

        while True:
            online_image.save(
                temp_image_path,
                format="JPEG",
                quality=quality,
                optimize=True,
            )

            if temp_image_path.stat().st_size <= LENS_MAX_BYTES:
                break

            if quality > 45:
                quality -= 10
            else:
                online_image.thumbnail(
                    (
                        max(1, online_image.width // 2),
                        max(1, online_image.height // 2),
                    )
                )
                quality = 75

            if online_image.width < 100 or online_image.height < 100:
                raise ValueError("Unable to compress the uploaded image.")

        yield temp_image_path

    finally:
        temp_image_path.unlink(missing_ok=True)


# --------------------------------------------------
# 6. Home and health-check endpoints
# --------------------------------------------------


@app.get("/")
def home():
    return {
        "app": "Vistora",
        "message": "Backend is working!",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


# SerpApi's account endpoint is free (it doesn't use a search), but it is
# still cached briefly so every page load doesn't call it.
USAGE_CACHE_SECONDS = 60
_usage_cache = {"at": 0.0, "data": None}
_usage_lock = threading.Lock()


def fetch_search_usage():
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is missing")
    response = requests.get(
        "https://serpapi.com/account.json", params={"api_key": api_key}, timeout=10
    )
    response.raise_for_status()
    account = response.json()
    data = {
        # SerpApi: photo search (and text search when Serper isn't set up).
        "searches_left": account.get("total_searches_left"),
        "searches_per_month": account.get("searches_per_month"),
        "used_this_month": account.get("this_month_usage"),
        "renews_on": account.get("plan_renewal_date"),
        "plan": account.get("plan_name"),
        "text": fetch_serper_usage(),
        "fast_photo": fetch_searchapi_usage(),
    }
    # The search code skips providers that are known to be empty.
    search_credits.record("serpapi", data["searches_left"])
    search_credits.record("serper", (data["text"] or {}).get("searches_left"))
    search_credits.record("searchapi", (data["fast_photo"] or {}).get("searches_left"))
    return data


def fetch_searchapi_usage():
    """SearchApi.io credits (fast photo search), or None when not set up."""
    api_key = os.getenv("SEARCHAPI_API_KEY")
    if not api_key or not os.getenv("BLOB_READ_WRITE_TOKEN"):
        return None
    try:
        response = requests.get(
            "https://www.searchapi.io/api/v1/me", params={"api_key": api_key}, timeout=10
        )
        response.raise_for_status()
        account = response.json().get("account") or response.json()
        left = int(account.get("remaining_credits") or 0)
    except Exception as exc:
        print(f"Could not read SearchApi usage: {exc}")
        return None
    return {"provider": "searchapi", "searches_left": left, "enabled": fast_photo.enabled()}


SERPER_CREDITS_PER_SEARCH = 2  # 40 results per Google Shopping request


def fetch_serper_usage():
    """Serper.dev credits (text search, photo-search prices), or None."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return None
    try:
        response = requests.get(
            "https://google.serper.dev/account", headers={"X-API-KEY": api_key}, timeout=10
        )
        response.raise_for_status()
        credits = int(response.json().get("balance") or 0)
    except Exception as exc:
        print(f"Could not read Serper usage: {exc}")
        return None
    return {
        "provider": "serper",
        "credits": credits,
        "searches_left": credits // SERPER_CREDITS_PER_SEARCH,
    }


@app.get("/api/v1/usage")
async def search_usage():
    """How many SerpApi searches are left this month (photo and text search)."""
    with _usage_lock:
        fresh = time.monotonic() - _usage_cache["at"] < USAGE_CACHE_SECONDS
        if fresh and _usage_cache["data"]:
            return _usage_cache["data"]
    try:
        data = await run_in_threadpool(fetch_search_usage)
    except Exception as exc:
        print(f"Could not read SerpApi usage: {exc}")
        raise HTTPException(status_code=503, detail="Search usage is unavailable right now.")
    with _usage_lock:
        _usage_cache.update(at=time.monotonic(), data=data)
    return data


# Below these many searches left a provider counts as "low" (the owner is
# warned before it runs out); SerpApi is also low under 10% of its plan.
LOW_SEARCHES = {
    "serpapi": int(os.getenv("LOW_CREDITS_SERPAPI", "25")),
    "searchapi": int(os.getenv("LOW_CREDITS_SEARCHAPI", "15")),
    "serper": int(os.getenv("LOW_CREDITS_SERPER", "50")),
}
STATUS_ORDER = ("ok", "low", "empty")


def provider_status(left, low_at, total=None):
    if left is None:
        return "ok"
    if left <= 0:
        return "empty"
    if left <= low_at or (total and left / total <= 0.1):
        return "low"
    return "ok"


def credit_status(usage):
    """{"status", "providers", "problems"}: the worst state across providers."""
    providers = {
        "serpapi": ("Photo and text searches (SerpApi)", usage.get("searches_left"), usage.get("searches_per_month")),
        "searchapi": ("Fast photo searches (SearchApi)", (usage.get("fast_photo") or {}).get("searches_left"), None),
        "serper": ("Text searches (Serper)", (usage.get("text") or {}).get("searches_left"), None),
    }
    report, problems, worst = {}, [], "ok"
    for key, (label, left, total) in providers.items():
        if left is None and key != "serpapi":
            continue  # not set up on this server
        state = provider_status(left, LOW_SEARCHES[key], total)
        report[key] = {"label": label, "left": left, "status": state}
        if state != "ok":
            problems.append(f"{label}: {'none left' if state == 'empty' else f'only {left} left'}")
        if STATUS_ORDER.index(state) > STATUS_ORDER.index(worst):
            worst = state
    return {"status": worst, "providers": report, "problems": problems, "renews_on": usage.get("renews_on")}


def with_cache_health(result, cache):
    """Add the shared cache's state; a cache that is set up but not working is a problem."""
    if cache is None:
        return result
    result["shared_cache"] = cache
    if not cache["ok"]:
        result["problems"].append(f"Shared cache (Upstash): {cache['detail']}")
        if result["status"] == "ok":
            result["status"] = "low"
    return result


@app.get("/api/v1/usage/status")
async def usage_status():
    """
    A health check for the search credits and the shared cache, for an uptime
    monitor (for example UptimeRobot) to watch: 200 while every provider has
    plenty left and the cache works, 503 once any is low or empty or the cache
    is not working, so the monitor emails the owner in time.
    """
    data = await search_usage()
    result = with_cache_health(credit_status(data), await run_in_threadpool(shared_cache.health))
    result["fast_photo"] = {"on": fast_photo.enabled()}
    if result["status"] != "ok":
        print(f"SEARCH CREDITS {result['status'].upper()}: {'; '.join(result['problems'])}")
        return JSONResponse(status_code=503, content=result)
    return result


def forget_search_usage():
    """A search just ran; read the count again next time."""
    with _usage_lock:
        _usage_cache["at"] = 0.0


# --------------------------------------------------
# 7. Identify the product in an uploaded image
# --------------------------------------------------


@app.post("/api/v1/products/recognize-image")
async def recognize_image(request: Request, file: UploadFile = File(...)):
    image = await read_uploaded_image(file)
    check_search_limit(request)

    def identify(image):
        with lens_ready_image(image) as image_path:
            return identify_product(image_path)

    try:
        # Run the blocking work off the event loop.
        result = await run_in_threadpool(identify, image)

    except Exception as exc:
        print(f"Product identification failed: {exc}")
        raise search_failure(exc)

    return {
        "message": "Product identification completed.",
        "query": result["query"],
        "top_titles": result["top_titles"],
        "note": (
            "The query is built from the titles of the closest "
            "Google Lens matches."
        ),
    }


# --------------------------------------------------
# 8. Cache results for repeated searches
# --------------------------------------------------

# Searching the same photo (or words) again is answered from the cache:
# instant, and it does not use another search credit. Results expire after
# CACHE_TTL_HOURS (default 24) because prices and stock change; the results
# page tells visitors how old a saved result is.
CACHE_TTL_SECONDS = int(float(os.getenv("CACHE_TTL_HOURS", "24")) * 3600)
CACHE_MAX_ENTRIES = 300

_search_cache = OrderedDict()
_search_cache_lock = threading.Lock()


def image_fingerprint(image: Image.Image) -> str:
    """Hash a small copy of the pixels, so re-saved copies of a photo still match."""
    # Hashing a downscaled copy is far cheaper than a multi-megapixel buffer.
    small = image.resize((96, 96), Image.BILINEAR, reducing_gap=2.0)
    digest = hashlib.sha256()
    digest.update(f"{image.width}x{image.height}".encode())
    digest.update(small.tobytes())
    return digest.hexdigest()


# A result found in the shared cache is kept in memory for this long only,
# since its real age is not known.
SHARED_HIT_MEMORY_SECONDS = 5 * 60


def get_cached_search(key):
    with _search_cache_lock:
        entry = _search_cache.get(key)

        if entry is not None:
            stored_at, result = entry
            if time.monotonic() - stored_at <= CACHE_TTL_SECONDS:
                _search_cache.move_to_end(key)
                return result
            del _search_cache[key]

    # Not in this instance's memory: another instance may have searched it.
    result = shared_cache.get(key) if shared_cache.enabled() else None
    if result is not None:
        store_cached_search(
            key, result, share=False, age_seconds=CACHE_TTL_SECONDS - SHARED_HIT_MEMORY_SECONDS
        )
    return result


def store_cached_search(key, result, ttl_seconds=CACHE_TTL_SECONDS, share=True, age_seconds=0):
    with _search_cache_lock:
        _search_cache[key] = (time.monotonic() - age_seconds, result)
        _search_cache.move_to_end(key)

        while len(_search_cache) > CACHE_MAX_ENTRIES:
            _search_cache.popitem(last=False)

    if share and shared_cache.enabled():
        shared_cache.put(key, result, ttl_seconds)


# --------------------------------------------------
# 9. Limit searches per client
# --------------------------------------------------

# Every uncached search spends SerpApi credit, so each client (by IP
# address) gets a limited number per time window. Cached results are free
# and do not count. Set SEARCH_LIMIT=0 in .env to turn the limit off.
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "10"))
SEARCH_WINDOW_SECONDS = int(os.getenv("SEARCH_WINDOW_SECONDS", "600"))

# Behind a hosting proxy (Hugging Face Spaces, Render, ...) every request
# arrives from the proxy, so the visitor's address must be read from
# X-Forwarded-For. Only enable this when a trusted proxy sets that header.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in {
    "true",
    "1",
    "yes",
}

_search_log = {}
_search_log_lock = threading.Lock()


def client_address(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop

    return request.client.host if request.client else "unknown"


def enforce_limit(request: Request, usage_log, limit, window_seconds, noun):
    """Record a request for this client, or raise 429 if over the limit."""
    if limit <= 0:
        return

    client = client_address(request)
    now = time.monotonic()

    with _search_log_lock:
        # Drop requests that have left the window (and idle clients).
        for key in list(usage_log):
            log = usage_log[key]
            while log and now - log[0] > window_seconds:
                log.popleft()
            if not log:
                del usage_log[key]

        log = usage_log.setdefault(client, deque())

        if len(log) >= limit:
            retry_after = int(window_seconds - (now - log[0])) + 1
            minutes = max(1, round(retry_after / 60))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You've reached the limit of {limit} {noun}. "
                    f"Please try again in about {minutes} "
                    f"minute{'s' if minutes != 1 else ''}."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        log.append(now)


def check_search_limit(request: Request):
    """Called before every uncached search, i.e. one that uses SerpApi."""
    enforce_limit(request, _search_log, SEARCH_LIMIT, SEARCH_WINDOW_SECONDS, "searches")
    forget_search_usage()


# --------------------------------------------------
# 10. Search online products using an image
# --------------------------------------------------


MAX_QUERY_LENGTH = 150  # room for a full sentence: "an hp laptop with 8gb ram..."


def clean_query(query: str | None) -> str | None:
    """Normalise an optional user-typed product query."""
    if not query:
        return None

    query = " ".join(query.split())[:MAX_QUERY_LENGTH]
    return query or None


def search_cache_key(image: Image.Image, query: str | None) -> str:
    # The same photo searched with different words is a different search.
    key = image_fingerprint(image)
    return f"{key}:{query.lower()}" if query else key


def run_search(image: Image.Image, on_event=None, query=None) -> dict:
    """Run the full online search for an image (blocking)."""
    with lens_ready_image(image) as image_path:
        return search_online_products(
            image_path=image_path,
            max_results=10,
            on_event=on_event,
            query=query,
        )


def build_search_response(online_results: dict) -> dict:
    """Shape the service result into the API response."""
    best_matches = online_results.get("best_matches", [])
    cheapest_alternatives = online_results.get("cheapest_alternatives", [])
    query = online_results.get("online_search_query", "")

    # Defensive validation in case the service returns unexpected data.
    if not isinstance(best_matches, list):
        best_matches = []

    if not isinstance(cheapest_alternatives, list):
        cheapest_alternatives = []

    return {
        "category": query,
        # Online visual matches.
        "best_matches": best_matches,
        "best_matches_count": len(best_matches),
        # Online products sorted by known price.
        "cheapest_alternatives": cheapest_alternatives,
        "cheapest_alternatives_count": len(cheapest_alternatives),
        # Combined online count.
        "online_count": len(best_matches) + len(cheapest_alternatives),
        "online_search_query": query,
        # Text search: what a natural-language request was understood as.
        "understood": online_results.get("understood"),
        # Photo search: cheaper lookalikes of the closest matches.
        "dupes": online_results.get("dupes") or [],
        "note": (
            "Best Matches are ranked by visual similarity and text relevance. "
            "Cheapest Alternatives are sorted by known numeric price. "
            "Online listings are candidates, not guaranteed identical "
            "products. Prices and availability may change."
        ),
    }


def cache_if_useful(cache_key, response, ttl_seconds=CACHE_TTL_SECONDS):
    # Only cache searches that found something, so a temporary Lens
    # failure is retried next time.
    found = response.get("best_matches") or response.get("cheapest_alternatives")
    # Outfits: cache when every item's search finished.
    items = response.get("items") or []
    if found or (items and not any(item.get("failed") for item in items)):
        # When it was saved, in milliseconds: shown as the result's age.
        response["saved_at"] = int(time.time() * 1000)
        store_cached_search(cache_key, response, ttl_seconds)
        return True
    return False


@app.post("/api/v1/products/search-by-image")
async def search_products_by_image(
    request: Request,
    file: UploadFile = File(...),
    query: str | None = Form(None),
):
    # Step 1: Validate and read the uploaded image.
    image = await read_uploaded_image(file)
    query = clean_query(query)

    cache_key = await run_in_threadpool(search_cache_key, image, query)
    cached = get_cached_search(cache_key)

    if cached is not None:
        print("Search served from cache.")
        return {**cached, "cached": True}

    check_search_limit(request)

    # Step 2: Search online. Google Lens identifies the product itself,
    # and the search query is derived from its results.
    try:
        # Run the blocking work off the event loop so other requests
        # are still served while a search is in progress.
        online_results = await run_in_threadpool(run_search, image, None, query)

    except Exception as exc:
        print(f"Online product search failed: {exc}")
        raise search_failure(exc)

    # Step 3: Return both online sections.
    response = build_search_response(online_results)
    cache_if_useful(cache_key, response)

    return {**response, "cached": False}


# --------------------------------------------------
# 11. Streamed search: show results as they become ready
# --------------------------------------------------


@app.post("/api/v1/products/search-by-image/stream")
async def search_products_by_image_stream(
    request: Request,
    file: UploadFile = File(...),
    query: str | None = Form(None),
):
    """
    Same search, streamed as newline-delimited JSON events:

        {"type": "stage", "stage": "identifying"}   search started
        {"type": "identified", "online_search_query": ...}
        {"type": "preview", "best_matches": [...], "cheapest_alternatives": [...],
         "online_search_query": ...}                 ranked, prices from Lens
        {"type": "final", ...same body as /search-by-image...}
        {"type": "error", "detail": ...}

    Preview listings with "pending": true are still having their price or
    stock checked; the final event replaces them.
    """
    # Validation errors are returned as normal HTTP errors before streaming.
    image = await read_uploaded_image(file)
    query = clean_query(query)

    cache_key = await run_in_threadpool(search_cache_key, image, query)
    cached = get_cached_search(cache_key)

    # Over-limit errors are also returned before streaming starts.
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="identifying",
        run=lambda emit: run_search(image, on_event=emit, query=query),
    )


def stream_search_response(cache_key, cached, first_stage, run, shape=None):
    """
    Stream a search as newline-delimited JSON events.

    run(emit) performs the blocking search in a worker thread and returns the
    service result; emit(event_type, payload) sends progress events. shape
    turns the result into the final response (default: product search).
    Exceptions marked user_facing send their own message.
    """
    shape = shape or build_search_response
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    done = object()

    def emit(event_type, payload=None):
        # Called from the worker thread; hand events to the event loop.
        event = {"type": event_type, **(payload or {})}
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker():
        try:
            emit("stage", {"stage": first_stage})
            response = shape(run(emit))
            cache_if_useful(cache_key, response)
            emit("final", {**response, "cached": False})
        except Exception as exc:
            print(f"Online product search failed: {exc}")
            detail = str(exc) if getattr(exc, "user_facing", False) else ONLINE_SEARCH_ERROR
            emit("error", {"detail": detail})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, done)

    async def events():
        if cached is not None:
            print("Search served from cache.")
            yield json.dumps({"type": "final", **cached, "cached": True}) + "\n"
            return

        task = loop.run_in_executor(None, worker)

        while True:
            event = await queue.get()
            if event is done:
                break
            yield json.dumps(event) + "\n"

        await task

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------
# 12. Search by typed text (Google Shopping)
# --------------------------------------------------


class TextSearchRequest(BaseModel):
    query: str


def text_query_or_400(body: TextSearchRequest) -> str:
    query = clean_query(body.query)
    if not query or len(query) < 2:
        raise HTTPException(
            status_code=400,
            detail="Type at least 2 characters to search.",
        )
    return query


def normalised_query(query: str) -> str:
    return " ".join(query.lower().split())


def text_cache_key(query: str) -> str:
    return f"text:{normalised_query(query)}"


@app.post("/api/v1/products/search-by-text")
async def search_products_by_text(request: Request, body: TextSearchRequest):
    query = text_query_or_400(body)
    cache_key = text_cache_key(query)
    shared_cache.count_query(normalised_query(query))

    cached = get_cached_search(cache_key)
    if cached is not None:
        print("Search served from cache.")
        return {**cached, "cached": True}

    check_search_limit(request)

    try:
        online_results = await run_in_threadpool(search_shopping_text, query, 10)
    except Exception as exc:
        print(f"Text search failed: {exc}")
        raise search_failure(exc)

    response = build_search_response(online_results)
    cache_if_useful(cache_key, response)
    return {**response, "cached": False}


@app.post("/api/v1/products/search-by-text/stream")
async def search_products_by_text_stream(request: Request, body: TextSearchRequest):
    """Same as /search-by-text, streamed like the photo search (stage, final, error)."""
    query = text_query_or_400(body)
    cache_key = text_cache_key(query)
    shared_cache.count_query(normalised_query(query))

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="searching",
        run=lambda emit: search_shopping_text(query, 10),
    )


# --------------------------------------------------
# 12b. Keep popular text searches warm
# --------------------------------------------------

# A daily job (see vercel.json) searches the most-searched queries ahead of
# time and stores them in the shared cache, so the next shopper gets them at
# once. Each query it has to search costs one Serper search (2 credits), so it
# is OFF unless WARM_LIMIT is set above 0, which also caps the queries per run;
# and it never runs when Serper is low, so visitors keep the credits.
WARM_LIMIT = int(os.getenv("WARM_LIMIT", "0"))
WARM_KEEP_SEARCHES = int(os.getenv("WARM_KEEP_SEARCHES", "300"))
# Longer than a day, so the next run lands before the last results expire.
WARM_TTL_SECONDS = int(os.getenv("WARM_TTL_SECONDS", str(26 * 60 * 60)))


def queries_to_warm(limit: int, day: int) -> list[str]:
    """The most-searched queries first, then seed searches (a different slice each day)."""
    queries = shared_cache.top_queries(limit)

    start = (day * limit) % len(POPULAR_SEARCHES)
    rotated = POPULAR_SEARCHES[start:] + POPULAR_SEARCHES[:start]

    unique = []
    for query in queries + rotated:
        if query not in unique:
            unique.append(query)
    return unique[:limit]


def warm_popular_searches(usage=None) -> dict:
    """Warm the popular searches. usage: the credit counts just read (see search_usage)."""
    if WARM_LIMIT <= 0:
        return {"skipped": "WARM_LIMIT is 0"}
    if not shared_cache.enabled():
        return {"skipped": "no shared cache is configured"}
    if not os.getenv("SERPER_API_KEY"):
        return {"skipped": "warming uses Serper, so it doesn't spend photo-search credits"}

    spare = ((usage or {}).get("text") or {}).get("searches_left")
    if spare is None:
        spare = search_credits.left("serper")
    if spare is not None and spare < WARM_KEEP_SEARCHES:
        return {"skipped": f"only {spare} text searches left; keeping them for visitors"}

    warmed, already_cached, failed = [], 0, 0

    for query in queries_to_warm(WARM_LIMIT, time.gmtime().tm_yday):
        cache_key = text_cache_key(query)

        if get_cached_search(cache_key) is not None:
            already_cached += 1
            continue

        try:
            response = build_search_response(search_shopping_text(query, 10))
        except Exception as exc:
            print(f"Could not warm {query!r}: {exc}")
            failed += 1
            continue

        if cache_if_useful(cache_key, response, WARM_TTL_SECONDS):
            warmed.append(query)
        else:
            failed += 1

    return {"warmed": warmed, "already_cached": already_cached, "failed": failed}


def require_secret(request: Request):
    """Admin and cron addresses need CRON_SECRET as a bearer token; without one set they do not exist."""
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=404, detail="Not found")

    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


class FastPhotoSwitch(BaseModel):
    on: bool
    hours: float = fast_photo.DEFAULT_HOURS


@app.get("/api/v1/admin/fast-photo")
async def fast_photo_state(request: Request):
    """Is the fast photo provider switched on? (needs CRON_SECRET)"""
    require_secret(request)
    return fast_photo.state()


@app.post("/api/v1/admin/fast-photo")
async def switch_fast_photo(request: Request, body: FastPhotoSwitch):
    """
    Switch the fast photo provider on for `hours` (default 4, at most 48), or off.
    It goes back off by itself, so the limited credits are not used up by accident.
    """
    require_secret(request)
    state = await run_in_threadpool(fast_photo.turn_on, body.hours) if body.on else await run_in_threadpool(fast_photo.turn_off)
    forget_search_usage()
    return state


@app.get("/api/v1/cron/warm")
async def warm_cache(request: Request):
    """Called by Vercel Cron, which sends CRON_SECRET as a bearer token."""
    require_secret(request)

    try:
        usage = await search_usage()  # the credit counts the job checks first
    except HTTPException:
        usage = None
    return await run_in_threadpool(warm_popular_searches, usage)


# --------------------------------------------------
# 13. Virtual try-on
# --------------------------------------------------

# Try-ons use the free Hugging Face GPU quota, so they have their own,
# stricter limit. Repeating the same photo and garment is cached and free.
TRYON_LIMIT = int(os.getenv("TRYON_LIMIT", "5"))
TRYON_WINDOW_SECONDS = int(os.getenv("TRYON_WINDOW_SECONDS", "600"))
_tryon_log = {}


@app.post("/api/v1/tryon")
async def virtual_try_on(
    request: Request,
    person: UploadFile = File(...),
    garment_url: str = Form(...),
    category: str = Form(...),
    garment_name: str = Form(""),
):
    """
    Render the uploaded person photo wearing a product's garment.

    category is "upper_body", "lower_body" or "dresses" (the product's
    tryon_category). Returns a JPEG image.
    """
    if category not in GARMENT_WORDS:
        raise HTTPException(status_code=400, detail="This item can't be tried on.")

    person_image = await read_uploaded_image(person)

    fingerprint = await run_in_threadpool(image_fingerprint, person_image)
    cache_key = f"tryon:{fingerprint}:{category}:{garment_url}"
    cached = get_cached_search(cache_key)

    if cached is None:
        enforce_limit(request, _tryon_log, TRYON_LIMIT, TRYON_WINDOW_SECONDS, "try-ons")
        try:
            cached = await run_in_threadpool(
                try_on, person_image, garment_url, category, garment_name[:200]
            )
        except TryOnError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            print(f"Try-on failed: {exc}")
            raise HTTPException(
                status_code=503,
                detail="The try-on service is busy right now. Please try again in a minute.",
            )
        store_cached_search(cache_key, cached)
        was_cached = "false"
    else:
        was_cached = "true"

    return Response(
        content=cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Tryon-Cached": was_cached},
    )


# Live try-on (sunglasses, watches) runs in the browser; it only needs the
# product photo without its background. The web app checks every glasses and
# watch listing in the results this way, so the limit is generous; it exists
# because each check fetches a remote image. Results have their own cache so
# they don't push searches out of the search cache.
OVERLAY_LIMIT = int(os.getenv("OVERLAY_LIMIT", "150"))
OVERLAY_CACHE_ENTRIES = 500
_overlay_log = {}
_overlay_cache = OrderedDict()
_overlay_cache_lock = threading.Lock()


@app.get("/api/v1/tryon/overlay")
async def try_on_overlay(request: Request, url: str, category: str):
    """
    Return a product photo (category "glasses" or "watch", the product's
    ar_category) as a PNG with its background removed.
    """
    if category not in ("glasses", "watch"):
        raise HTTPException(status_code=400, detail="This item can't be tried on live.")
    if len(url) > 2048:
        raise HTTPException(status_code=400, detail="This product image can't be used.")

    cache_key = (category, url)
    with _overlay_cache_lock:
        cached = _overlay_cache.get(cache_key)
        if cached is not None:
            _overlay_cache.move_to_end(cache_key)

    if cached is None:
        enforce_limit(request, _overlay_log, OVERLAY_LIMIT, TRYON_WINDOW_SECONDS, "live try-ons")
        try:
            cached = await run_in_threadpool(product_overlay, url, category)
        except TryOnError as exc:
            cached = str(exc)
        except Exception as exc:
            print(f"Overlay failed: {exc}")
            raise HTTPException(
                status_code=422,
                detail="Couldn't prepare this product's photo. Try another listing.",
            )
        # Unusable photos are cached too, so they aren't fetched again.
        with _overlay_cache_lock:
            _overlay_cache[cache_key] = cached
            while len(_overlay_cache) > OVERLAY_CACHE_ENTRIES:
                _overlay_cache.popitem(last=False)

    if isinstance(cached, str):
        raise HTTPException(status_code=422, detail=cached)

    png, centres = cached
    headers = {"Cache-Control": "public, max-age=86400"}
    if centres:
        headers["X-Lens-Centres"] = ",".join(f"{value:.4f}" for value in centres)
    return Response(content=png, media_type="image/png", headers=headers)


# --------------------------------------------------
# Find the outfit
# --------------------------------------------------


@app.post("/api/v1/outfit/stream")
async def find_outfit_stream(request: Request, file: UploadFile = File(...)):
    """
    Identify everything the person in the photo wears and find shopping
    options for each item, streamed as newline-delimited JSON events:
    "stage", "items" (the identified items with approximate boxes), one
    "item" per item as its results arrive, then "final" (or "error").
    """
    image = await read_uploaded_image(file)
    fingerprint = await run_in_threadpool(image_fingerprint, image)
    cache_key = f"outfit:{fingerprint}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="identifying",
        run=lambda emit: find_outfit(image, on_event=emit),
        shape=lambda outfit: outfit,
    )


# --------------------------------------------------
# Complete the look
# --------------------------------------------------


class LookRequest(BaseModel):
    name: str
    price: float | None = None


@app.post("/api/v1/look/stream")
async def complete_the_look_stream(request: Request, body: LookRequest):
    """
    Suggest the items that go with a product and find shopping options for
    each, streamed like Find the outfit: "stage", "items", one "item" per
    item, then "final" (or "error").
    """
    name = clean_query(body.name)
    if not name or len(name) < 3:
        raise HTTPException(status_code=400, detail="This product has no name to style around.")
    cache_key = f"look:{name.lower()}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="styling",
        run=lambda emit: complete_the_look(name, on_event=emit, product_price=body.price),
        shape=lambda look: look,
    )


# --------------------------------------------------
# Shopping assistant chat
# --------------------------------------------------

# The assistant uses Groq's free tier only (no searches), with its own limit.
ASSISTANT_LIMIT = int(os.getenv("ASSISTANT_LIMIT", "30"))
ASSISTANT_WINDOW_SECONDS = int(os.getenv("ASSISTANT_WINDOW_SECONDS", "600"))
_assistant_log = {}


class AssistantRequest(BaseModel):
    messages: list[dict]
    products: list[dict]
    query: str = ""


@app.post("/api/v1/assistant")
async def shopping_assistant(request: Request, body: AssistantRequest):
    """Answer a question about the products on screen: {reply, picks, search}."""
    enforce_limit(request, _assistant_log, ASSISTANT_LIMIT, ASSISTANT_WINDOW_SECONDS, "questions")
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=503, detail="The assistant isn't set up on this server yet.")

    try:
        return await run_in_threadpool(ask_assistant, body.messages, body.products, body.query)
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


# --------------------------------------------------
# Personal styling: rate my outfit, colours that suit you
# --------------------------------------------------

# Colour analysis only uses the vision model (no searches); its own limit.
STYLE_LIMIT = int(os.getenv("STYLE_LIMIT", "10"))
STYLE_WINDOW_SECONDS = int(os.getenv("STYLE_WINDOW_SECONDS", "600"))
_style_log = {}


@app.post("/api/v1/style/rate/stream")
async def rate_outfit_stream(
    request: Request,
    file: UploadFile = File(...),
    colours: str | None = Form(default=None),
):
    """
    Rate the outfit in a photo and shop the suggested changes, streamed:
    "stage", "rating" (score, rubric scores, verdict, occasion, strengths),
    "items", one "item" per suggestion, then "final" (or "error").
    colours: optional comma-separated best colours to prefer in the fixes.
    """
    image = await read_uploaded_image(file)
    fingerprint = await run_in_threadpool(image_fingerprint, image)
    palette = [c.strip() for c in (colours or "").split(",") if c.strip()][:10]
    cache_key = f"rate:{fingerprint}:{','.join(palette).lower()}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="rating",
        run=lambda emit: rate_outfit(image, on_event=emit, colours=palette),
        shape=lambda rated: rated,
    )


@app.post("/api/v1/style/colours")
async def colours_that_suit(request: Request, file: UploadFile = File(...)):
    """
    The clothing colours that suit the person in a selfie: {undertone,
    season, summary, best: [{name, hex}], avoid}. The selfie isn't kept.
    """
    enforce_limit(request, _style_log, STYLE_LIMIT, STYLE_WINDOW_SECONDS, "colour checks")
    image = await read_uploaded_image(file)
    try:
        return await run_in_threadpool(analyse_colours, image)
    except OutfitError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --------------------------------------------------
# Compare products
# --------------------------------------------------


class CompareRequest(BaseModel):
    products: list[dict]
    query: str = ""


@app.post("/api/v1/compare")
async def compare(request: Request, body: CompareRequest):
    """Compare 2-3 listings side by side: {attributes, pros, best, verdict}."""
    enforce_limit(request, _assistant_log, ASSISTANT_LIMIT, ASSISTANT_WINDOW_SECONDS, "questions")
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=503, detail="Compare isn't set up on this server yet.")
    try:
        return await run_in_threadpool(compare_products, body.products, body.query)
    except AssistantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


# --------------------------------------------------
# Shop this room
# --------------------------------------------------


@app.post("/api/v1/room/stream")
async def shop_the_room_stream(request: Request, file: UploadFile = File(...)):
    """
    Find the furniture and decor in a room photo and shop each piece,
    streamed like Find the outfit: "stage", "items", one "item" per piece,
    then "final" (with the room's "style") or "error".
    """
    image = await read_uploaded_image(file)
    fingerprint = await run_in_threadpool(image_fingerprint, image)
    cache_key = f"room:{fingerprint}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="identifying",
        run=lambda emit: find_room(image, on_event=emit),
        shape=lambda room: room,
    )


# --------------------------------------------------
# Budget look planner
# --------------------------------------------------


class PlanRequest(BaseModel):
    request: str
    budget: float | None = None
    gender: str | None = None


@app.post("/api/v1/plan/stream")
async def plan_a_look_stream(request: Request, body: PlanRequest):
    """
    Plan a whole look within a budget and shop it, streamed: "stage",
    "plan" (title, budget, gender), "items", one "item" per piece, then
    "final" with the picked listing per piece ("picks") and the "total".
    """
    text = clean_query(body.request) or ""
    gender = (body.gender or "").strip().lower() or None
    try:
        budget = await run_in_threadpool(read_budget_or_400, text, body.budget)
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    cache_key = f"plan:{text.lower()}:{budget:.0f}:{gender or ''}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="planning",
        run=lambda emit: plan_look(text, budget, gender, on_event=emit),
        shape=lambda plan: plan,
    )


def read_budget_or_400(text, budget):
    """The plan's budget (given, or read from the request); PlanError if none."""
    if len(text) < 3:
        raise PlanError("Describe the look you want, e.g. \"wedding outfit for men under ₹5,000\".")
    return read_budget(text, budget)


# --------------------------------------------------
# Gift finder
# --------------------------------------------------


class GiftRequest(BaseModel):
    request: str
    budget: float | None = None


@app.post("/api/v1/gifts/stream")
async def gift_finder_stream(request: Request, body: GiftRequest):
    """
    Six gift ideas with listings, streamed: "stage", "gifts" (title,
    recipient, budget), "items", one "item" per idea, then "final".
    """
    text = clean_query(body.request) or ""
    if len(text) < 3:
        raise HTTPException(status_code=400, detail="Say who the gift is for, e.g. \"brother who loves the gym\".")
    cache_key = f"gifts:{text.lower()}:{body.budget or ''}"

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="thinking",
        run=lambda emit: find_gifts(text, body.budget, on_event=emit),
        shape=lambda gifts: gifts,
    )


# --------------------------------------------------
# Snap your shopping list
# --------------------------------------------------

MAX_LIST_TEXT = 2000


@app.post("/api/v1/list/stream")
async def shopping_list_stream(
    request: Request,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """
    Read a shopping list (a photo in `file`, or typed `text`) and shop every
    line, streamed: "stage", "list" (title), "items", one "item" per line,
    then "final" with the picked listing per line and the cart "total".
    """
    if file is not None:
        image = await read_uploaded_image(file)
        fingerprint = await run_in_threadpool(image_fingerprint, image)
        cache_key = f"list:{fingerprint}"
        run = lambda emit: shop_list(image=image, on_event=emit)  # noqa: E731
    else:
        typed = " ".join((text or "").split())[:MAX_LIST_TEXT]
        if len(typed) < 3:
            raise HTTPException(status_code=400, detail="Write or photograph a shopping list first.")
        cache_key = f"list-text:{typed.lower()}"
        run = lambda emit: shop_list(text=typed, on_event=emit)  # noqa: E731

    cached = get_cached_search(cache_key)
    if cached is None:
        check_search_limit(request)

    return stream_search_response(
        cache_key,
        cached,
        first_stage="reading",
        run=run,
        shape=lambda shopped: shopped,
    )


# --------------------------------------------------
# Price watch
# --------------------------------------------------

# Each check reads store pages and may use a Google Shopping search per
# product, so visitors get a few checks an hour.
WATCH_LIMIT = int(os.getenv("WATCH_LIMIT", "6"))
WATCH_WINDOW_SECONDS = int(os.getenv("WATCH_WINDOW_SECONDS", "3600"))
_watch_log = {}


class PriceCheckRequest(BaseModel):
    items: list[dict]


@app.post("/api/v1/prices/check")
async def check_watched_prices(request: Request, body: PriceCheckRequest):
    """
    Current prices of watched products: {"results": [{"id", "price",
    "original_price", "availability", "source", "status"}]}, status being
    "down", "up", "same" or "unknown" against the price sent.
    """
    enforce_limit(request, _watch_log, WATCH_LIMIT, WATCH_WINDOW_SECONDS, "price checks")
    try:
        results = await run_in_threadpool(check_prices, body.items)
    except PriceWatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"results": results}
