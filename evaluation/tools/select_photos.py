"""
Build the test set from the chosen candidate photos and write the answer key.

Every photo is a real photograph from Wikimedia Commons (free licence). Three
different photos per product, chosen by eye so the angle, lighting and
background differ. labels.json is the answer key: a listing counts as the
right product when its title names the brand AND the model.
"""

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# product slug -> display name, brand words (any), model words (any), and for each
# photo: (candidate folder, file, what makes this photo different)
PRODUCTS = {
    "casio-f91w": {
        "name": "Casio F-91W digital watch",
        "brand": ["casio"],
        "model": ["f-91w", "f91w"],
        "photos": [
            ("casio-f91w", "01.jpg", "front view on a white background"),
            ("casio-f91w", "04.jpg", "close-up of the face, strap cropped"),
            ("casio-f91w", "11.jpg", "tilted, dark studio background"),
        ],
    },
    "converse-chuck-taylor": {
        "brand_needed": True,
        "name": "Converse Chuck Taylor All Star",
        "brand": ["converse"],
        "model": ["chuck taylor", "all star", "all-star"],
        "photos": [
            ("converse-chuck-taylor", "01.jpg", "side view of a cream high-top, grey backdrop"),
            ("converse-chuck-taylor", "07.jpg", "top-down view of red high-tops on wood"),
            ("converse-chuck-taylor", "12.jpg", "angled red low-tops on a shoebox"),
        ],
    },
    "apple-airpods-max": {
        "name": "Apple AirPods Max",
        "brand": ["apple"],
        "model": ["airpods max"],
        "photos": [
            ("apple-airpods", "13.jpg", "front view on a white background"),
            ("apple-airpods", "05.jpg", "flat lay on a bamboo mat"),
            ("apple-airpods", "06.jpg", "on a stand against a textured wall"),
        ],
    },
    "ray-ban-wayfarer": {
        "brand_needed": True,
        "name": "Ray-Ban Wayfarer sunglasses",
        "brand": ["ray-ban", "ray ban", "rayban"],
        "model": ["wayfarer"],
        "photos": [
            ("ray-ban-wayfarer", "06.jpg", "angled studio shot on a lilac backdrop"),
            ("ray-ban-wayfarer", "09.jpg", "another angle, graduated lenses"),
            ("ray-ban-wayfarer", "10.jpg", "extreme close-up of the temple and logo"),
        ],
    },
    "nike-air-force-1": {
        "name": "Nike Air Force 1",
        "brand": ["nike"],
        "model": ["air force 1", "air force one", "air force"],
        "photos": [
            ("nike-air-force-1", "01.jpg", "pair seen from above, indoor, on the box"),
            ("nike-air-force-1", "05.jpg", "side view on the box, dark background"),
            ("nike-air-force-1", "12.jpg", "outdoors, angled pair on asphalt"),
        ],
    },
    "apple-watch": {
        "name": "Apple Watch",
        "brand": ["apple"],
        "model": ["apple watch"],
        "photos": [
            ("apple-watch", "06.jpg", "lying flat beside its white box"),
            ("apple-watch", "04.jpg", "angled, yellow sport band, clean render-like shot"),
            ("apple-watch", "05.jpg", "worn on a wrist, dial facing the camera"),
        ],
    },
    "amazon-kindle-paperwhite": {
        "name": "Amazon Kindle Paperwhite",
        "brand": ["kindle", "amazon"],
        "model": ["paperwhite"],
        "photos": [
            ("amazon-kindle", "08.jpg", "front view on a white background"),
            ("amazon-kindle", "10.jpg", "lying on pavement outdoors, angled"),
            ("amazon-kindle", "11.jpg", "propped up beside a coffee cup, cafe light"),
        ],
    },
    "jbl-flip": {
        "brand_needed": True,
        "name": "JBL Flip Bluetooth speaker",
        "brand": ["jbl"],
        "model": ["flip"],
        "photos": [
            ("jbl-flip", "01.jpg", "black speaker end-on, desk, soft light"),
            ("jbl-flip", "04.jpg", "beige speaker lying flat on wood"),
            ("jbl-flip", "05.jpg", "blue speaker from above with its charger"),
        ],
    },
    "logitech-mx-master": {
        "name": "Logitech MX Master mouse",
        "brand": ["logitech"],
        "model": ["mx master"],
        "photos": [
            ("logitech-mx-master", "02.jpg", "three-quarter view on a grey backdrop"),
            ("logitech-mx-master", "04.jpg", "from above, scroll wheel visible"),
            ("logitech-mx-master", "12.jpg", "from the front, USB-C port visible"),
        ],
    },
    "adidas-stan-smith": {
        "name": "Adidas Stan Smith",
        "brand": ["adidas"],
        "model": ["stan smith"],
        "photos": [
            ("adidas-stan-smith", "04.jpg", "pair on a wooden floor, indoor"),
            ("adidas-stan-smith", "05.jpg", "single shoe at an angle, indoor light"),
            ("adidas-stan-smith", "07.jpg", "pair with black heel tab and price tag"),
        ],
    },
    "samsung-galaxy-buds": {
        "name": "Samsung Galaxy Buds",
        "brand": ["samsung"],
        "model": ["galaxy buds"],
        "photos": [
            ("samsung-galaxy-buds", "05.jpg", "open case on a wooden table"),
            ("samsung-galaxy-buds", "07.jpg", "open case, close-up, blurred background"),
            ("samsung-galaxy-buds", "03.jpg", "case open on top of a phone, dark background"),
        ],
    },
}


def main():
    photos_dir = ROOT / "photos"
    if photos_dir.exists():
        shutil.rmtree(photos_dir)
    labels, credits = [], []
    for slug, product in PRODUCTS.items():
        folder = photos_dir / slug
        folder.mkdir(parents=True, exist_ok=True)
        for number, (candidate, file, variant) in enumerate(product["photos"], 1):
            source = ROOT / "candidates" / candidate / file
            target = folder / f"{number}.jpg"
            shutil.copy(source, target)
            info = next(
                item for item in json.loads((ROOT / "candidates" / candidate / "info.json").read_text(encoding="utf8"))
                if item["file"] == file
            )
            labels.append({
                "id": f"{slug}/{number}",
                "product": slug,
                "name": product["name"],
                "brand": product["brand"],
                "model": product["model"],
                "brand_needed": product.get("brand_needed", False),
                "variant": variant,
                "file": f"photos/{slug}/{number}.jpg",
            })
            credits.append([f"{slug}/{number}", info["title"], info["page"], info["licence"], info["author"]])
    (ROOT / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf8")
    with open(ROOT / "photo_credits.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["photo", "commons file", "page", "licence", "author"])
        writer.writerows(credits)
    print(f"{len(labels)} photos of {len(PRODUCTS)} products")


if __name__ == "__main__":
    main()
