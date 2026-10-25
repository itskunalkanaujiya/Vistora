"""
Price accuracy: for a sample of the correct listings Vistora showed with a price,
open the seller's page and compare the price on the page with the price shown.

This calls no search provider (only the stores' own pages, like a shopper
clicking the link), so it costs no search credits. Pages that block automated
requests, or do not show a price in a form that can be read, are counted as
"could not check", not as right or wrong.

The pages are read some minutes to hours after the search, so a small
difference can also be a real price change, not an error.
"""

import csv
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import analyze  # noqa: E402
from image_shopping_service import fetch_page_details  # noqa: E402

SAMPLE = 60
SEED = 2026


def candidates():
    labels, runs = analyze.load()
    rows = []
    for id_, run in runs.items():
        row = analyze.analyse_photo(labels[id_], run)
        if not row:
            continue
        for listing, verdict in zip(row["_pool"], row["_pool_verdicts"]):
            if verdict == "exact" and listing.get("price") is not None and listing.get("product_url"):
                rows.append((id_, listing))
    return rows


def main():
    rows = candidates()
    random.Random(SEED).shuffle(rows)
    sample = rows[:SAMPLE]
    print(f"{len(rows)} correct listings with a price; checking {len(sample)}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda item: fetch_page_details(item[1]["product_url"]), sample))

    results = []
    for (id_, listing), page in zip(sample, pages):
        shown = float(listing["price"])
        host = urlparse(listing["product_url"]).netloc.replace("www.", "")
        if not page["fetched"]:
            status, found, difference = "page blocked or unreachable", None, None
        elif page["price"] is None:
            status, found, difference = "no readable price on the page", None, None
        elif page.get("currency") not in (None, "INR"):
            status, found, difference = f"page price in {page['currency']}", None, None
        else:
            found = float(page["price"])
            difference = (found - shown) / shown
            status = "checked"
        results.append({"photo": id_, "store": host, "shown": shown, "page": found,
                        "difference": None if difference is None else round(difference, 4), "status": status})

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    with open(out / "price_check.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    checked = [r for r in results if r["status"] == "checked"]
    absolute = sorted(abs(r["difference"]) for r in checked)
    summary = {
        "listings_checked_attempted": len(results),
        "page_opened": sum(r["status"] != "page blocked or unreachable" for r in results),
        "price_read_and_compared": len(checked),
        "could_not_check": len(results) - len(checked),
        "within_1_percent": round(sum(a <= 0.01 for a in absolute) / len(absolute), 4) if absolute else None,
        "within_5_percent": round(sum(a <= 0.05 for a in absolute) / len(absolute), 4) if absolute else None,
        "within_15_percent": round(sum(a <= 0.15 for a in absolute) / len(absolute), 4) if absolute else None,
        "median_absolute_difference": round(absolute[len(absolute) // 2], 4) if absolute else None,
        "shown_higher_than_page": sum(r["difference"] < -0.01 for r in checked),
        "shown_lower_than_page": sum(r["difference"] > 0.01 for r in checked),
        "by_reason": {s: sum(r["status"] == s for r in results) for s in {r["status"] for r in results}},
    }
    (out / "price_check.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
