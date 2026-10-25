"""
Find candidate test photos for the evaluation on Wikimedia Commons (free
licences), several per product, so angle, light and background vary by
themselves. Nothing here touches the search providers, so it costs no credits.

    python fetch_candidates.py            # all products
    python fetch_candidates.py casio-f91w # one product

Writes evaluation/candidates/<product>/NN.jpg and info.json (title, page,
licence, author) for the picker to choose from.
"""

import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "candidates"
UA = "VistoraEvaluation/1.0 (student project; local evaluation, small downloads)"
API = "https://commons.wikimedia.org/w/api.php"

# slug -> Commons search text
PRODUCTS = {
    "casio-f91w": "Casio F-91W",
    "converse-chuck-taylor": "Converse Chuck Taylor All Star",
    "apple-airpods": "Apple AirPods",
    "sony-wh-1000xm4": "Sony WH-1000XM4",
    "ray-ban-wayfarer": "Ray-Ban Wayfarer",
    "nike-air-force-1": "Nike Air Force 1",
    "apple-watch": "Apple Watch",
    "amazon-kindle": "Amazon Kindle",
    "jbl-flip": "JBL Flip speaker",
    "logitech-mx-master": "Logitech MX Master",
    "adidas-stan-smith": "Adidas Stan Smith",
    "samsung-galaxy-buds": "Samsung Galaxy Buds",
}


# Products the first test set did not include, for checking changes on photos not tuned against.
FRESH = {
    "nintendo-switch": "Nintendo Switch console",
    "gopro-hero": "GoPro Hero camera",
    "sony-dualsense": "Sony DualSense controller",
    "vans-old-skool": "Vans Old Skool",
    "fitbit-charge": "Fitbit Charge",
    "canon-eos": "Canon EOS camera",
    "oneplus-buds": "OnePlus Buds",
    "bose-quietcomfort": "Bose QuietComfort headphones",
    "crocs-classic-clog": "Crocs Classic Clog",
}


def curl(url, output=None):
    command = ["curl", "-sL", "-m", "60", "-A", UA, url]
    if output:
        command += ["-o", str(output)]
    result = subprocess.run(command, capture_output=True)
    return result.stdout


def api(**params):
    url = API + "?" + urllib.parse.urlencode({"format": "json", **params})
    return json.loads(curl(url))


def candidates(query, limit=14):
    data = api(
        action="query",
        generator="search",
        gsrsearch=f"{query} filetype:bitmap",
        gsrnamespace=6,
        gsrlimit=limit,
        prop="imageinfo",
        iiprop="url|size|mime|extmetadata",
        iiurlwidth=960,
        iiextmetadatafilter="LicenseShortName|Artist|ImageDescription",
    )
    found = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") != "image/jpeg" or not info.get("thumburl"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 500:
            continue
        meta = info.get("extmetadata", {})
        found.append({
            "title": page["title"],
            "page": info.get("descriptionurl"),
            "thumb": info["thumburl"],
            "licence": (meta.get("LicenseShortName") or {}).get("value", ""),
            "author": re.sub("<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:80],
            "description": re.sub("<[^>]+>", "", (meta.get("ImageDescription") or {}).get("value", ""))[:160],
        })
    return found


def main(only):
    fresh = "--fresh" in only
    only = only - {"--fresh"}
    products, out = (FRESH, ROOT / "candidates_fresh") if fresh else (PRODUCTS, OUT)
    for slug, query in products.items():
        if only and slug not in only:
            continue
        folder = out / slug
        folder.mkdir(parents=True, exist_ok=True)
        found = candidates(query)
        kept = []
        for number, item in enumerate(found, 1):
            target = folder / f"{number:02d}.jpg"
            curl(item["thumb"], target)
            if target.exists() and target.stat().st_size > 5000:
                kept.append({"file": target.name, **item})
            time.sleep(0.4)
        (folder / "info.json").write_text(json.dumps(kept, indent=1), encoding="utf8")
        print(f"{slug}: {len(kept)} candidate photos")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
