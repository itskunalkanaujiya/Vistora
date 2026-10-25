# Vistora

Upload a photo of a product — or type what you're looking for — and Vistora
AI finds matching listings across online stores in India, with prices and
stock availability.

- **Best matches**: listings that look most like your photo
- **Lowest prices**: the cheapest listings, in-stock items first
- **Saved items**: keep listings in your browser to compare later

## How it works

**Virtual try-on** shows the user wearing a garment from the results. Clothing
listings (tops, kurtis, shirts, bottoms, dresses) get a "Try on" button; the
user adds a photo and the backend sends it with the product image to free
try-on models on Hugging Face: [Leffa](https://huggingface.co/spaces/franciszzj/Leffa)
(MIT) first, then [IDM-VTON](https://huggingface.co/spaces/yisol/IDM-VTON)
(non-commercial) as a fallback for tops. A try-on takes about 20–40 seconds
on Hugging Face's free GPU quota.

**Glasses and watch try-on** ("Try on" on sunglasses, glasses and watches)
works on a photo, like the clothes try-on. The person uploads a photo of
their face or wrist; in the browser,
[MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)
finds the eyes or the hand, and the product's real photo, cut out of its
background by the backend (`/api/v1/tryon/overlay`), is placed on it: frames
on the eyes, the watch on the wrist along the arm. The person's photo never
leaves the device. Glasses are sized from both the pupils and the width of
the face and placed by matching the lens centres in the product photo to the
pupils; the cut-out's edges are cleaned of the white photo background,
tinted lenses are slightly see-through and a soft shadow sits under the
frame, so they look worn rather than pasted on. Size and position sliders
fine-tune the fit, with a before/after slider and a download. The web app checks
each listing's photo in the background and shows "Try on" only when it is
usable: a plain background and, for glasses, a front view (both lenses found
and alike, as clear-lens holes or tinted areas), so the frame on the face is
always the real product photo.

**Gift finder.** The "Find a gift" tool: who it's for, the occasion, what they like
and a budget, in any words ("bhai ke liye, gym ka shauk, 2000 tak"). A Groq
model suggests six varied ideas, each with a reason; each is searched and
checked by the listing judge, and listings well over the budget are left out
(`backend/gift_service.py`).

**Shop my list.** A photo of a handwritten list or a chat screenshot ("Shop
my list" tool), or a typed list ("Type your list instead" on that page). The
vision model (or, for typed lists, a language model) reads each line into an
English search with its quantity and any budget, in Hindi or Hinglish too;
each line is searched and checked, the best listing at about the typical
price is picked per line (within a written budget when there is one) and the
cart total counts quantities (`backend/list_service.py`).

**Price watch.** The bell on a card watches its price; the watch list lives
in the browser (no account). When the app opens, watches older than 12 hours
are re-checked (`/api/v1/prices/check`, `backend/price_watch_service.py`):
from the store page when the link is one, else the same store's Google
Shopping listing whose title matches closely (the nearest price among
near-identical listings; a jump of over 60% counts as a different product,
not a drop). Drops show a banner and, with permission, a browser
notification; the Saved page lists every watch with its history. Alerts
appear when the app is opened, not while it's closed.

**Budget look planner.** The "Plan a look on a budget" tool: an occasion ("wedding guest
outfit"), who it's for and a total budget (or a budget in the sentence, "2k
tak"). A Groq model plans 3-5 pieces and splits the budget between them
(`backend/planner_service.py`); each piece is searched and checked by the
listing judge within its share, then one listing is picked per piece so the
total stays within budget (the piece with the most to save steps down to a
cheaper option until it fits). Users can swap any piece; the total and the
budget bar update.

**Shop this room.** Like Find the outfit, for a photo of a room
(`backend/room_service.py`): the vision model lists up to 8 pieces of
furniture, lighting and decor with boxes, each is searched and re-ranked
against its crop (CLIP), with the price of the whole room.

**Compare.** A "Compare" checkbox on every card; with 2 or 3 picked, a bar
opens a side-by-side table (price, store, rating) plus the features a Groq
model reads from the names (RAM, material, display...), each product's
strong points, a best pick and a verdict (`compare_products` in
`backend/assistant_service.py`).

**Rate my outfit.** Next to Find the outfit: the vision model scores the
look out of 10, says what works, and suggests 2-3 new items to add or swap
(`backend/style_service.py`), each searched like an outfit item so every tip
is shoppable. It judges only clothes and styling, never the person.

**Colours that suit you.** "My colours" in the header: from a selfie, the
vision model reads undertone and contrast and returns a seasonal palette in
shopping colour words. The selfie isn't kept; the palette stays in the
browser. Listings whose names mention one of the colours (or a synonym:
burgundy for maroon, ivory for cream) get a "Suits you" badge, and a
"My colours" filter shows only those.

**Fake discount detector.** When a listing has a "was" price (SerpApi
Google Shopping, or the MRP read from the store page during a photo
search), a big claimed discount on a price no lower than similar listings
is flagged "Discount looks inflated"; a claimed discount that is also below
the typical price is a "Real discount". Serper's shopping results carry no
"was" prices, so typed searches through Serper don't get this check.

**Complete the look.** Every product card has a "Complete the look" button:
a Groq text model suggests 3-4 items that go with it (chinos and loafers
for a shirt, a bag and a mouse for a laptop), each with a one-line reason,
and every item is searched in parallel and shown like Find the outfit, with
the price of the whole look.

**Shopping assistant chat.** "Ask AI about these" opens a chat about the
listings on screen. The assistant answers from their names, prices, stores,
ratings and review counts only (in English, Hindi or Hinglish), links the
listings it recommends and can suggest a new search. It uses Groq's free
tier, with its own limit (ASSISTANT_LIMIT, 30 questions per 10 minutes).

**Deal score, dupes and Hinglish voice search.** Every result shows how its
price compares with the typical (median) price of that search ("Great deal ·
30% below typical"). Photo searches add **Cheaper lookalikes**: listings at
least "Similar" to the photo (CLIP ≥ 0.78) costing at most 70% of the
closest matches, with the saving shown. Text search accepts Hindi and
Hinglish ("50k ke andar 8GB RAM wala laptop"), typed or spoken through the
browser's speech recognition (English or Hindi).

**Find the outfit.** For a photo of a person, a vision model
(`backend/outfit_service.py`) checks them head to toe (headwear, eyewear,
jewellery, outerwear, top, drapes such as dupattas and sarees, bottom, belt,
watch, bag, footwear) and lists up to 8 items, each with a shopping
description and a box, in about 2 s. Gemini Flash is used when
`GEMINI_API_KEY` is set (it finds more items and boxes them better), with
Qwen3.8 27B on Groq as the fallback. The photo is padded to a square before
it's sent, so boxes land on the right item in portrait photos too.

Every item is then searched on Google Shopping (through Serper) in
parallel, taking a wide pool of listings with only a loose title match, and
the listings are re-ranked by how much their photos look like the item's
crop from the photo (CLIP): ones clearly less alike than the best match, and
ones priced over 4× the item's typical price, are dropped. A whole outfit
uses no Google Lens searches; **Exact match** on an item runs a photo search
(Lens) on just its crop, with a way back to the outfit.

**Search providers.** Each search uses the provider that did best in our
side-by-side tests: photo search uses Google Lens through **SearchApi.io**
first (5–9 s where SerpApi took 9–41 s, same matches) while its credits last.
SearchApi only reads images from a public link, so the photo is put on a
public **Vercel Blob** store under an unguessable name and deleted as soon as
the search returns. Otherwise photo search uses **SerpApi** (prices and
Indian stores), text search uses Google Shopping through **Serper.dev**
(faster and more relevant), falling back to SerpApi if Serper isn't set up,
fails or runs out. After Lens identifies a photo's product, a background
Serper Shopping lookup fills prices Lens left out, from the same store's
matching listing. The home screen shows the searches left on each.

**Text search understands sentences.** "a laptop of 8gb ram with 500gb
storage and company hp under 50k" is read (`backend/query_understanding.py`)
as brand HP, product laptop, 8 GB RAM, ~500 GB storage and a ₹50,000 budget:
Google Shopping is searched for "hp laptop 8GB RAM 500GB", the budget is a
hard limit, and listings are ranked by how many requirements their titles
meet (512 GB counts as ~500 GB). The results page shows what was understood.
Plain keyword searches work as before. With `GROQ_API_KEY` set, sentence-style
requests are also read by a language model (Groq free tier: Qwen3.8 27B, GPT-OSS 20B as backup;
`backend/llm_query_parser.py`), which understands looser phrasing ("a phone
good for gaming that lasts all day", "something to keep my tea hot") and
suggests the search query. Numbers and budgets written in the request always
come from the rule-based reader, and any model error or delay over 4 s falls
back to it.

**Text search** sends the typed query to Google Shopping:
top results keep Google's relevance order, and Lowest Prices are the
cheapest listings that still contain most of the query's words. Listings
show ratings and original prices where stores provide them, and link to
Google Shopping's page comparing the stores that sell the item.

**Photo search:**

1. The photo is sent to **Google Lens** (through [SerpApi](https://serpapi.com/google-lens-api)).
   No search text is needed — Lens identifies the product, and Vistora builds
   a short product query from the titles of the matching listings.
2. Non-shopping and non-product pages are filtered out, and duplicates removed.
3. **CLIP** (the ViT-B/32 image encoder, from
   [kunalkanaujiya/clip-vit-base-patch32-vision](https://huggingface.co/kunalkanaujiya/clip-vit-base-patch32-vision))
   re-ranks listings by visual similarity to your photo.
4. Missing prices and stock status are read from seller pages (structured
   product data, page metadata, and Amazon/Flipkart-specific markup).

## Project structure

```
backend/                     FastAPI server
  main.py                    API endpoints, upload validation, cache, rate limits
  image_shopping_service.py  Google Lens search, CLIP ranking, price and stock extraction
  text_shopping_service.py   Google Shopping search and relevance scoring
  tryon_service.py           Clothing try-on (Hugging Face) and product cut-outs
  tests/                     Offline tests
  requirements.txt
  .env.example               Copy to .env and add your SerpApi key
frontend/                    React 19 + Vite app
  src/App.jsx                App state and page layout
  src/components/            Search panels, results, product cards, try-on dialogs
  src/lib/products.js        Price, filter and formatting helpers
  src/lib/tryon.js           Clothing try-on requests
  src/lib/accessoryTryOn.js  Face/hand detection and product placement
```

## Setup

Requirements: Python 3.13, Node.js 20+, and a [SerpApi](https://serpapi.com) API key.

### Backend

```bash
cd backend
python -m venv ../myvenv
../myvenv/Scripts/activate        # macOS/Linux: source ../myvenv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then put your SerpApi key in .env
uvicorn main:app --host 127.0.0.1 --port 8000
```

The first start downloads the CLIP image encoder (about 176 MB). API docs are at
http://127.0.0.1:8000/docs.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. To point the app at a different backend, set
`VITE_API_URL` (for example in `frontend/.env.local`).

### Tests

The backend tests run offline: Google Lens, CLIP and seller pages are
replaced with fakes, so no SerpApi credit is used.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

## Deployment

Both parts run on Vercel as two projects connected to this repository; every
push to `main` redeploys them.

| Project | Root directory | Address | Settings |
|---|---|---|---|
| `vistora` (frontend) | `frontend` | https://vistora-app.vercel.app | `VITE_API_URL=https://vistora-api.vercel.app` |
| `vistora-api` (backend) | `backend` | https://vistora-api.vercel.app | `SERPAPI_API_KEY` (encrypted), `TRUST_PROXY_HEADERS`, `ALLOWED_ORIGIN_REGEX`, `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` |

The backend bundle includes CPU-only PyTorch (about 1 GB), so it uses Vercel's
large functions. On a cold start it loads PyTorch and downloads the CLIP image
encoder to `/tmp`, so the first search after an idle period is slower. The
result cache and search limit are kept per server instance.

The `backend/Dockerfile` builds the same backend as a container for any Docker
host.

## Keeping search credits from running out

Search runs on paid providers (SerpApi, SearchApi.io, Serper.dev), and each
has a limited number of searches. Three things protect the app:

- **Skipping empty providers.** When a provider was last read as having no
  searches left, searches skip it instead of waiting for a call that will fail,
  and go to the next provider. If every provider is empty, visitors see a clear
  "search is at its limit" message (HTTP 503) instead of a generic failure;
  searches already run still load from the cache.
- **Warning you early.** `GET /api/v1/usage/status` answers `200` while every
  provider has plenty left and `503` (with a list of what is low) once one gets
  low. Point a free uptime monitor at it (for example
  [UptimeRobot](https://uptimerobot.com), HTTP monitor, 5-minute interval) and it
  emails you before searches stop. A provider counts as low at 25 searches
  (SerpApi, or under 10% of its plan), 15 (SearchApi) or 50 (Serper); change
  these with `LOW_CREDITS_SERPAPI`, `LOW_CREDITS_SEARCHAPI` and
  `LOW_CREDITS_SERPER`.
- **Showing visitors.** The footer shows what is left on each provider.

The same address also checks the shared cache below: if Upstash is set up but
rejects the token or can't be reached, it answers `503` and names the problem,
so a mistyped token doesn't go unnoticed.

Top up or upgrade a plan on the provider's site before it reaches zero.

### Shared cache and warm searches (optional)

Without it, each server instance remembers results only in its own memory,
and Vercel starts instances empty. With a free [Upstash Redis](https://upstash.com)
database, every instance shares one cache, so a search anyone ran in the last
hour (photo or text) is answered in about 0.01 s.

In the `vistora-api` project settings add `UPSTASH_REDIS_REST_URL` and
`UPSTASH_REDIS_REST_TOKEN` (adding Upstash Redis from the Vercel Marketplace
sets `KV_REST_API_URL` and `KV_REST_API_TOKEN`, which also work), then
redeploy. If Redis is unreachable, searches carry on using memory only.

A daily Vercel Cron job (`/api/v1/cron/warm`, 07:00 India time, set in
`backend/vercel.json`) also searches the most-searched typed queries ahead of
time, filling up with the seed list in `backend/popular_searches.py`, and keeps
them for 26 hours. Set `CRON_SECRET` in Vercel (any long random string) so only
the cron can call it. Each query it has to search costs one Serper search
(2 credits), so the job is **off by default**: set `WARM_LIMIT` above 0 in Vercel
(for example 4) to turn it on and cap the queries per run. It skips the run when
Serper has fewer than
`WARM_KEEP_SEARCHES` (default 300) searches left. Warmed prices can be up to a
day old.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/products/search-by-image` | Upload an image (`file`, JPEG/PNG/WebP, max 8 MB) and optionally a `query` (up to 150 characters, e.g. a brand or model) to narrow the Lens search; returns `best_matches` and `cheapest_alternatives` |
| `POST` | `/api/v1/products/search-by-image/stream` | Same search as newline-delimited JSON events: `stage`, `identified`, `preview` (ranked listings with Google Lens prices; `pending: true` while a seller page is still being checked), then `final` (same body as above) or `error`. Used by the web app. |
| `POST` | `/api/v1/products/search-by-text` | JSON body `{"query": "..."}` (2–150 characters, keywords or a sentence like "hp laptop with 8gb ram under 50k"); searches Google Shopping and returns the same sections as the photo search, plus `understood` (what a sentence was read as) |
| `POST` | `/api/v1/products/search-by-text/stream` | Same, streamed as `stage` then `final` (or `error`) events |
| `POST` | `/api/v1/products/recognize-image` | Identify the product only; returns the derived query and top Lens titles |
| `POST` | `/api/v1/tryon` | Multipart: `person` (photo), `garment_url` (product image), `category` (`upper_body`, `lower_body` or `dresses`, from the product's `tryon_category`), optional `garment_name`; returns a JPEG |
| `GET` | `/api/v1/tryon/overlay` | Query `url` (product image) and `category` (`glasses` or `watch`, from the product's `ar_category`); returns the photo as a PNG with its background removed, for the live try-on |
| `POST` | `/api/v1/outfit/stream` | Upload a photo of a person (`file`); streams `stage`, `items` (identified items with `type`, `description`, `query`, `box` as fractions), one `item` per item with its `best_matches` and `cheapest_alternatives`, then `final` (or `error`). Needs `GROQ_API_KEY` |
| `GET` | `/api/v1/usage` | Searches left: SerpApi plan, Serper credits (`text`, when `SERPER_API_KEY` is set) and SearchApi credits (`fast_photo`, when `SEARCHAPI_API_KEY` and `BLOB_READ_WRITE_TOKEN` are set) |
| `GET` | `/health` | Health check |

## Notes

- Each search uses one SerpApi search (two if Google Lens returns nothing and
  Vistora retries). Identical photos and searches are served from a cache for `CACHE_TTL_HOURS` (default 24) hours, and the results page says how old a saved result is.
- To protect your SerpApi quota, each client (IP address) can run 10 uncached
  searches per 10 minutes; further searches get HTTP 429 with a `Retry-After`
  header. Change this with `SEARCH_LIMIT` and `SEARCH_WINDOW_SECONDS` in
  `backend/.env` (`SEARCH_LIMIT=0` turns it off).
- Try-ons use Hugging Face's free ZeroGPU quota for the `HF_TOKEN` account
  (locally, your `hf auth login`), limited to 5 per visitor per 10 minutes
  (`TRYON_LIMIT` / `TRYON_WINDOW_SECONDS`). The public Spaces can be busy or
  down; IDM-VTON is non-commercial, so use only Leffa for commercial use.
- Match labels come from CLIP similarity: **Very close** (≥ 0.88, usually the
  same item), **Similar** (≥ 0.78) and **Related** (same kind of product).
  These thresholds were calibrated on real searches and live in
  `frontend/src/lib/products.js`.
- Prices and stock are read at search time and may change. Some stores block
  automated price checks, so a few listings show "Price on store".
- On Windows, run uvicorn **without** `--reload`; the auto-reloader can stall
  and keep serving old code.

## Credits

The 3D emoji pictures in `frontend/public/emoji/` are from Microsoft's
[Fluent Emoji](https://github.com/microsoft/fluentui-emoji), used under the
MIT licence (Copyright (c) Microsoft Corporation).
