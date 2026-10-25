"""
Work out the evaluation metrics from the saved runs. Reads labels.json and
runs/*.json only: no search provider is called, so this costs nothing and can
be re-run as often as needed.

Writes results/per_photo.csv, results/judged_top5.csv (every judged listing, to
check the automatic judging by eye), results/metrics.json and results/summary.md.
"""

import csv
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
# EVAL_SET=fresh works on the second set of photos (labels_fresh.json, runs_fresh/, results_fresh/).
SET = ("_" + os.environ["EVAL_SET"]) if os.environ.get("EVAL_SET") else ""
LABELS = ROOT / f"labels{SET}.json"
RUNS = ROOT / f"runs{SET}"
RESULTS = ROOT / f"results{SET}"

# Words that make a listing an accessory for the product, not the product itself.
ACCESSORY = re.compile(
    r"\b(protector|screen ?guards?|tempered|skins?|wraps?|covers?|case cover|silicone|protective|"
    r"replacement|refill|stickers?|charger|charging cable|cables?|adapter|stands?|holders?|docks?|"
    r"pouch|sleeve|ear ?tips?|ear ?pads?|cushions?|laces?|insoles?|cleaner|compatible|fits?|bumper|"
    r"screen film)\b"
    r"|\bfor (?:the )?(?:casio|apple|samsung|jbl|logitech|adidas|nike|converse|kindle|amazon|ray-?ban|airpods)\b",
    re.IGNORECASE,
)

# How each test photo was taken (from looking at it).
CONDITION = {
    "casio-f91w/1": "clean backdrop", "casio-f91w/2": "close-up", "casio-f91w/3": "clean backdrop",
    "converse-chuck-taylor/1": "clean backdrop", "converse-chuck-taylor/2": "real-world", "converse-chuck-taylor/3": "real-world",
    "apple-airpods-max/1": "clean backdrop", "apple-airpods-max/2": "real-world", "apple-airpods-max/3": "real-world",
    "ray-ban-wayfarer/1": "clean backdrop", "ray-ban-wayfarer/2": "clean backdrop", "ray-ban-wayfarer/3": "close-up",
    "nike-air-force-1/1": "real-world", "nike-air-force-1/2": "real-world", "nike-air-force-1/3": "real-world",
    "apple-watch/1": "clean backdrop", "apple-watch/2": "clean backdrop", "apple-watch/3": "real-world",
    "amazon-kindle-paperwhite/1": "clean backdrop", "amazon-kindle-paperwhite/2": "real-world", "amazon-kindle-paperwhite/3": "real-world",
    "jbl-flip/1": "real-world", "jbl-flip/2": "real-world", "jbl-flip/3": "real-world",
    "logitech-mx-master/1": "clean backdrop", "logitech-mx-master/2": "clean backdrop", "logitech-mx-master/3": "clean backdrop",
    "adidas-stan-smith/1": "real-world", "adidas-stan-smith/2": "real-world", "adidas-stan-smith/3": "real-world",
    "samsung-galaxy-buds/1": "real-world", "samsung-galaxy-buds/2": "close-up", "samsung-galaxy-buds/3": "real-world",
}

MARKETPLACES = {
    "Amazon": ("amazon",), "Flipkart": ("flipkart",), "Myntra": ("myntra",), "Ajio": ("ajio",),
    "Croma": ("croma",), "Tata CLiQ": ("tatacliq", "tata cliq"), "Reliance Digital": ("reliancedigital", "reliance digital"),
    "Snapdeal": ("snapdeal",), "JioMart": ("jiomart",), "Nykaa": ("nykaa",), "Meesho": ("meesho",),
    "Decathlon": ("decathlon",), "Vijay Sales": ("vijaysales", "vijay sales"),
}

# News, review and video pages: about the product, but not something you can buy.
ARTICLE = re.compile(
    r"\b(launched|leak(?:ed|s)?|hands-on|review|unboxing|rumou?rs?|announce[ds]?|everything you need|how to)\b",
    re.IGNORECASE,
)

SLOW_SECONDS = 20
# The first run of the first set ran while the image model was still loading; its time is left out.
COLD_RUN = "casio-f91w/1"  # the searches where the fast provider failed and the backup was used


def norm(text):
    text = (text or "").lower().replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", text)


def mentions(title, phrases):
    plain, packed = norm(title), re.sub(r"[\s-]", "", norm(title))
    return any(p in plain or re.sub(r"[\s-]", "", p) in packed for p in phrases)


def judge(title, label):
    """'exact' (the product), 'accessory', 'article' (news or review), 'brand' (right brand, not the model) or 'other'."""
    model = mentions(title, label["model"])
    brand = mentions(title, label["brand"])
    if ARTICLE.search(norm(title)) and (model or brand):
        return "article"
    if ACCESSORY.search(norm(title)) and (model or brand):
        return "accessory"
    if model and (brand or not label["brand_needed"]):
        return "exact"
    return "brand" if brand else "other"


def store_of(listing):
    text = norm(f"{listing.get('marketplace') or ''} {urlparse(listing.get('product_url') or '').netloc}")
    for name, keys in MARKETPLACES.items():
        if any(k in text for k in keys):
            return name
    return None


def percentile(values, share):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def load():
    labels = {label["id"]: label for label in json.loads(LABELS.read_text(encoding="utf8"))}
    runs = {}
    for path in sorted(RUNS.glob("*.json")):
        if path.name == "backend.log":
            continue
        run = json.loads(path.read_text(encoding="utf8"))
        runs[run["id"]] = run
    return labels, runs


def analyse_photo(label, run):
    final = next((e for e in run["events"] if e["type"] == "final"), None)
    if not final:
        return None
    best = final.get("best_matches") or []
    cheap = final.get("cheapest_alternatives") or []
    pool, seen = [], set()
    for listing in best + cheap:
        key = listing.get("product_url") or listing.get("name")
        if key not in seen:
            seen.add(key)
            pool.append(listing)

    verdicts = [judge(l.get("name"), label) for l in best]
    pool_verdicts = [judge(l.get("name"), label) for l in pool]
    exact_pool = sum(v == "exact" for v in pool_verdicts)

    def precision(k):
        top = verdicts[:k]
        return sum(v == "exact" for v in top) / len(top) if top else None

    def recall(k):
        return sum(v == "exact" for v in verdicts[:k]) / exact_pool if exact_pool else None

    exact_listings = [l for l, v in zip(pool, pool_verdicts) if v == "exact"]
    top10 = verdicts[:10]
    timings = run["timings"]
    stores = {store_of(l) for l in exact_listings} - {None}
    return {
        "id": label["id"], "product": label["product"], "variant": label["variant"],
        "condition": label.get("condition") or CONDITION[label["id"]], "query": final.get("online_search_query") or "",
        "listings_best": len(best), "listings_pool": len(pool), "exact_in_pool": exact_pool,
        "p@5": precision(5), "p@10": precision(10),
        "hit@1": int(bool(verdicts[:1]) and verdicts[0] == "exact"),
        "hit@5": int("exact" in verdicts[:5]), "hit@10": int("exact" in verdicts[:10]),
        "recall@5": recall(5), "recall@10": recall(10),
        "brand@1": int(bool(verdicts[:1]) and verdicts[0] in ("exact", "brand", "accessory")),
        "accessory_top10": sum(v == "accessory" for v in top10) / len(top10) if top10 else None,
        "price_rate_exact": (sum(l.get("price") is not None for l in exact_listings) / len(exact_listings))
        if exact_listings else None,
        "price_rate_all": sum(l.get("price") is not None for l in pool) / len(pool) if pool else None,
        "major_marketplaces_exact": len(stores),
        "t_first": timings.get("preview_lens"), "t_ranked": timings.get("preview_ranked"),
        "t_final": timings.get("final"), "slow": int((timings.get("final") or 0) >= SLOW_SECONDS),
        "_best": best, "_verdicts": verdicts, "_pool": pool, "_pool_verdicts": pool_verdicts,
    }


def summarise(rows):
    fields = ["p@5", "p@10", "hit@1", "hit@5", "hit@10", "recall@5", "recall@10", "brand@1",
              "accessory_top10", "price_rate_exact", "price_rate_all", "major_marketplaces_exact"]
    return {f: mean([r[f] for r in rows]) for f in fields}


def latency(rows):
    out = {}
    for name, key in (("first results (Google Lens matches)", "t_first"),
                      ("ranked results (visual re-rank)", "t_ranked"),
                      ("finished (with seller-page prices)", "t_final")):
        values = [r[key] for r in rows if r[key] is not None]
        if values:
            out[name] = {"n": len(values), "median": round(statistics.median(values), 2),
                         "p95": round(percentile(values, 0.95), 2), "mean": round(statistics.mean(values), 2),
                         "min": round(min(values), 2), "max": round(max(values), 2)}
    return out


def main():
    RESULTS.mkdir(exist_ok=True)
    labels, runs = load()
    rows = [r for r in (analyse_photo(labels[i], runs[i]) for i in labels if i in runs) if r]

    # The first search ran while the image model was still loading: its time is not representative.
    timed = [r for r in rows if r["id"] != COLD_RUN]
    by_product, by_condition = defaultdict(list), defaultdict(list)
    for r in rows:
        by_product[r["product"]].append(r)
        by_condition[r["condition"]].append(r)

    stores = Counter()
    for r in rows:
        for listing, verdict in zip(r["_pool"], r["_pool_verdicts"]):
            if verdict == "exact":
                stores[listing.get("marketplace") or urlparse(listing.get("product_url") or "").netloc] += 1
    major_found = Counter()
    for r in rows:
        for listing, verdict in zip(r["_pool"], r["_pool_verdicts"]):
            if verdict == "exact" and store_of(listing):
                major_found[store_of(listing)] += 1

    metrics = {
        "photos": len(rows), "products": len(by_product),
        "overall": summarise(rows),
        "by_product": {p: summarise(v) for p, v in by_product.items()},
        "by_condition": {c: {"photos": len(v), **summarise(v)} for c, v in by_condition.items()},
        "latency_all": latency(timed),
        "latency_without_fallbacks": latency([r for r in timed if not r["slow"]]),
        "fallback_searches": sum(r["slow"] for r in timed),
        "distinct_stores_with_exact_listings": len(stores),
        "top_stores": stores.most_common(12),
        "major_marketplaces_with_exact_listings": major_found.most_common(),
    }
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf8")

    columns = [k for k in rows[0] if not k.startswith("_")]
    with open(RESULTS / "per_photo.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    with open(RESULTS / "judged_top5.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["photo", "rank", "verdict", "store", "price", "title"])
        for r in rows:
            for rank, (listing, verdict) in enumerate(zip(r["_best"][:5], r["_verdicts"][:5]), 1):
                writer.writerow([r["id"], rank, verdict, listing.get("marketplace"), listing.get("price_text"), listing.get("name")])
    print(json.dumps({k: metrics[k] for k in ("photos", "products", "overall", "fallback_searches")}, indent=1))


if __name__ == "__main__":
    main()
