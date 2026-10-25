"""
The second, fresh test set: five products and photos that the first set (and the
changes made after it) never saw, used to check a change on photos it was not
tuned against. Same answer-key rules as select_photos.py.
"""

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# slug -> name, brand words, model phrases (any), brand needed?, photos: (candidate file, condition, description)
PRODUCTS = {
    "nintendo-switch": {
        "name": "Nintendo Switch", "brand": ["nintendo"], "model": ["nintendo switch"], "brand_needed": False,
        "photos": [
            ("02.jpg", "clean backdrop", "console in its dock with Joy-Con grips, white background"),
            ("05.jpg", "real-world", "blue Switch Lite on a wooden shelf"),
            ("01.jpg", "real-world", "grey Switch Lite photographed on a table, glare on the screen"),
        ],
    },
    "gopro-hero": {
        "name": "GoPro Hero action camera", "brand": ["gopro"], "model": ["gopro"], "brand_needed": False,
        "photos": [
            ("01.jpg", "real-world", "camera in its frame, dark studio background"),
            ("07.jpg", "real-world", "two cameras side by side on a wooden table"),
            ("09.jpg", "real-world", "small cube camera on its mount"),
        ],
    },
    "sony-dualsense": {
        "name": "Sony DualSense controller", "brand": ["sony", "playstation"], "model": ["dualsense"], "brand_needed": False,
        "photos": [
            ("01.jpg", "clean backdrop", "pearl controller from above on white"),
            ("06.jpg", "real-world", "white controller from above on a dark rough surface"),
            ("11.jpg", "clean backdrop", "black controller angled on white"),
        ],
    },
    "bose-quietcomfort": {
        "name": "Bose QuietComfort headphones", "brand": ["bose"], "model": ["quietcomfort", "quiet comfort"], "brand_needed": False,
        "photos": [
            ("04.jpg", "clean backdrop", "angled on a white background"),
            ("05.jpg", "clean backdrop", "headphones beside their carry case on white"),
            ("06.jpg", "real-world", "wireless pair hanging on a hook against a wooden door"),
        ],
    },
    "fitbit-charge": {
        "name": "Fitbit Charge", "brand": ["fitbit"], "model": ["fitbit charge", "charge hr"], "brand_needed": False,
        "photos": [
            ("01.jpg", "real-world", "worn on a wrist outdoors"),
            ("02.jpg", "real-world", "unfolded on a table with the heart-rate light on"),
            ("04.jpg", "real-world", "worn on a wrist, front view"),
        ],
    },
}


def main():
    photos_dir = ROOT / "photos_fresh"
    if photos_dir.exists():
        shutil.rmtree(photos_dir)
    labels, credits = [], []
    for slug, product in PRODUCTS.items():
        folder = photos_dir / slug
        folder.mkdir(parents=True, exist_ok=True)
        info_all = json.loads((ROOT / "candidates_fresh" / slug / "info.json").read_text(encoding="utf8"))
        for number, (file, condition, variant) in enumerate(product["photos"], 1):
            shutil.copy(ROOT / "candidates_fresh" / slug / file, folder / f"{number}.jpg")
            info = next(item for item in info_all if item["file"] == file)
            labels.append({
                "id": f"{slug}/{number}", "product": slug, "name": product["name"],
                "brand": product["brand"], "model": product["model"], "brand_needed": product["brand_needed"],
                "variant": variant, "condition": condition, "file": f"photos_fresh/{slug}/{number}.jpg",
            })
            credits.append([f"{slug}/{number}", info["title"], info["page"], info["licence"], info["author"]])
    (ROOT / "labels_fresh.json").write_text(json.dumps(labels, indent=1), encoding="utf8")
    with open(ROOT / "photo_credits_fresh.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["photo", "commons file", "page", "licence", "author"])
        writer.writerows(credits)
    print(f"{len(labels)} fresh photos of {len(PRODUCTS)} products")


if __name__ == "__main__":
    main()
