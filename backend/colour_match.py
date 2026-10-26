"""
Colour check for photo searches.

Titles are coarse ("kids frock" matches a green frock as well as the orange one
in the photo) and the visual model weighs shape over colour. So: read the photo's
main colours, read the colours a listing's title names, and call it a mismatch
when the title names colours and none of them is in the photo. A mismatch only
moves a listing below equally good ones; it never removes it.
"""

import colorsys
import re

# What each colour word in a title can look like in a photo.
COLOUR_WORDS = {
    "black": {"black"},
    "charcoal": {"black", "grey"},
    "white": {"white"},
    "ivory": {"white", "beige"},
    "cream": {"white", "beige"},
    "grey": {"grey"},
    "gray": {"grey"},
    "silver": {"grey", "white"},
    "red": {"red"},
    "maroon": {"red", "brown", "purple"},
    "wine": {"red", "purple"},
    "burgundy": {"red", "purple"},
    "orange": {"orange"},
    "rust": {"orange", "red", "brown"},
    "peach": {"orange", "pink", "beige"},
    "coral": {"orange", "pink", "red"},
    "yellow": {"yellow"},
    "mustard": {"yellow", "orange", "brown"},
    "gold": {"yellow", "orange", "brown", "beige"},
    "golden": {"yellow", "orange", "brown", "beige"},
    "green": {"green"},
    "olive": {"green", "brown"},
    "teal": {"green", "blue"},
    "mint": {"green", "white"},
    "blue": {"blue"},
    "navy": {"blue", "black"},
    "sky": {"blue"},
    "purple": {"purple"},
    "violet": {"purple"},
    "lavender": {"purple", "pink"},
    "pink": {"pink"},
    "magenta": {"pink", "purple"},
    "rose": {"pink", "red"},
    "brown": {"brown"},
    "tan": {"brown", "beige"},
    "beige": {"beige", "brown", "white"},
    "khaki": {"beige", "green", "brown"},
}
# Black, white, silver and the like are the usual variants of the same product
# (every phone and watch comes in them), so naming only these claims nothing.
NEUTRAL_WORDS = {"black", "charcoal", "white", "ivory", "cream", "grey", "gray", "silver", "beige", "tan", "khaki"}
# "Multi-colour" listings and similar make no colour claim.
NO_CLAIM = re.compile(r"\b(multi\s*-?colou?r|multicolou?red|assorted|combo|pack of|set of)\b", re.I)
WORD = re.compile(r"[a-z]+")

# Share of the middle of the photo a colour needs to count as in the photo.
MIN_SHARE = 0.10
MAX_COLOURS = 5
SAMPLE_SIZE = 48


def pixel_colour(r, g, b):
    """A basic colour name for one RGB pixel."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.2:
        return "black"
    if s < 0.12:
        return "white" if v > 0.85 else "grey"
    degrees = h * 360
    if s < 0.3 and v > 0.75 and 15 <= degrees < 60:
        return "beige"
    if degrees < 12 or degrees >= 345:
        return "pink" if v > 0.8 and s < 0.5 else "red"
    if degrees < 40:
        return "brown" if v < 0.65 else "orange"
    if degrees < 70:
        return "yellow" if v >= 0.65 else "brown"
    if degrees < 165:
        return "green"
    if degrees < 255:
        return "blue"
    if degrees < 300:
        return "purple"
    return "pink"


def photo_colours(image):
    """
    The main colours of a photo (a set of names). Only the middle of the photo is
    read, since the product is usually there and the edges are background.
    """
    image = image.convert("RGB")
    width, height = image.size
    box = (width * 0.2, height * 0.15, width * 0.8, height * 0.85)
    small = image.crop(tuple(round(v) for v in box)).resize((SAMPLE_SIZE, SAMPLE_SIZE))

    counts = {}
    for pixel in small.getdata():
        name = pixel_colour(*pixel)
        counts[name] = counts.get(name, 0) + 1

    total = SAMPLE_SIZE * SAMPLE_SIZE
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    return {name for name, count in ranked[:MAX_COLOURS] if count / total >= MIN_SHARE}


def title_colours(title):
    """The colour words a listing title names, or an empty list when it claims no real colour."""
    if not title or NO_CLAIM.search(title):
        return []
    named = [word for word in WORD.findall(title.lower()) if word in COLOUR_WORDS]
    return named if any(word not in NEUTRAL_WORDS for word in named) else []


def colour_mismatch(title, photo):
    """
    True when the title names colours and none of them can be seen in the photo.
    Always False when the photo's colours are unknown.
    """
    if not photo:
        return False
    named = title_colours(title)
    if not named:
        return False
    possible = set().union(*(COLOUR_WORDS[word] for word in named))
    return not (possible & photo)
