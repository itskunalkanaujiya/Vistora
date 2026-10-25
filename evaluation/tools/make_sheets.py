"""Make a numbered contact sheet per product so the best test photos can be chosen by eye."""

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CELL = 250
COLUMNS = 5


def sheet(folder):
    items = json.loads((folder / "info.json").read_text(encoding="utf8"))
    if not items:
        return None
    rows = (len(items) + COLUMNS - 1) // COLUMNS
    canvas = Image.new("RGB", (COLUMNS * CELL, rows * (CELL + 22)), "white")
    draw = ImageDraw.Draw(canvas)
    for index, item in enumerate(items):
        x, y = (index % COLUMNS) * CELL, (index // COLUMNS) * (CELL + 22)
        with Image.open(folder / item["file"]) as photo:
            photo = photo.convert("RGB")
            photo.thumbnail((CELL - 6, CELL - 6))
            canvas.paste(photo, (x + 3 + (CELL - 6 - photo.width) // 2, y + 22 + (CELL - 6 - photo.height) // 2))
        draw.text((x + 6, y + 4), f"{item['file'][:2]}  {item['title'][5:40]}", fill="black")
    path = folder / "sheet.png"
    canvas.save(path)
    return path


if __name__ == "__main__":
    import sys
    base = ROOT / ("candidates_fresh" if "--fresh" in sys.argv else "candidates")
    for folder in sorted(base.iterdir()):
        if folder.is_dir() and (folder / "info.json").exists():
            print(folder.name, sheet(folder))
