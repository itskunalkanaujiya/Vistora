"""
Virtual try-on: show a person wearing a product from the search results.

Clothing uses free public try-on models on Hugging Face Spaces through
gradio_client: Leffa (MIT licence) first, IDM-VTON (non-commercial licence)
as a fallback for upper-body garments. Both run on Hugging Face's free
ZeroGPU quota, which is tied to the HF_TOKEN account.

Sunglasses and watches are tried on live in the browser (face and hand
tracking); the backend only cuts the product photo out of its background.
"""

import io
import ipaddress
import os
import re
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

TRYON_SIZE = (768, 1024)  # width, height the models are trained on (3:4)
MAX_GARMENT_BYTES = 8 * 1024 * 1024
MODEL_TIMEOUT_SECONDS = 150

LEFFA_SPACE = os.getenv("TRYON_LEFFA_SPACE", "franciszzj/Leffa")
IDM_SPACE = os.getenv("TRYON_IDM_SPACE", "yisol/IDM-VTON")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
}

# Product words that identify a wearable garment, by try-on category.
GARMENT_WORDS = {
    "upper_body": {
        "shirt", "tshirt", "t-shirt", "tee", "top", "kurti", "kurta", "blouse",
        "sweater", "sweatshirt", "hoodie", "jacket", "blazer", "coat", "cardigan",
        "tunic", "polo", "jersey", "pullover", "crop top", "shrug", "vest",
    },
    "lower_body": {
        "jean", "jeans", "trouser", "trousers", "pant", "pants", "short", "shorts",
        "skirt", "legging", "leggings", "jogger", "joggers", "palazzo", "chino",
        "chinos", "cargo", "cargos",
    },
    "dresses": {"dress", "gown", "jumpsuit", "frock", "maxi", "romper", "playsuit"},
}

# Products that mention a garment word but are not garments.
NOT_GARMENT = re.compile(
    r"\b(watch|shoe|shoes|sneaker|bag|wallet|belt|cap|hat|sunglass|glasses|"
    r"earbud|phone|case|cover|hanger|pattern|fabric|cloth material|mannequin|"
    r"doll|toy|sticker|poster|mug|frame|socks?)\b",
    re.IGNORECASE,
)


# Accessories tried on live in the browser, and lookalikes that are not.
GLASSES_PATTERN = re.compile(
    r"\b(sun ?glass(es)?|spectacles?|eye ?glass(es)?|eyewear|goggles?|"
    r"glasses|(optical|eye|spectacle|computer) frames?)\b",
    re.IGNORECASE,
)
WATCH_PATTERN = re.compile(r"\b(wrist ?watch(es)?|smart ?watch(es)?|watch(es)?)\b", re.IGNORECASE)
NOT_ACCESSORY = re.compile(
    r"\b(wine|beer|whisky|whiskey|drinking|juice|water|shot|cocktail|champagne|"
    r"tea|coffee|glassware|tumblers?|magnifying|safety|swimming|vr|3d|"
    r"protector|tempered|screen ?guard|case|cover|box|pouch|holder|cleaner|"
    r"cleaning|stand|charger|cable|dock|winder|replacement|"
    r"watch (straps?|bands?)|(straps?|bands?) for|"
    r"(sun ?glass(es)?|glasses|spectacles?|eyewear) (chains?|cords?|straps?)|"
    r"lens(es)? only|toy|sticker|poster|print|printed)\b",
    re.IGNORECASE,
)

OVERLAY_MAX_SIZE = 640
BACKGROUND_TOLERANCE = 32  # colour distance still counted as background
MIN_PLAIN_BORDER = 0.6  # share of the border that must be plain background
MIN_LENS_AREA = 0.015  # enclosed areas this big (share of image) are clear lenses
MIN_GLASSES_RATIO = 1.25  # glasses photos are wide; taller ones show a model
# In a front view both lenses look alike; in an angled view the far lens is
# narrower and shorter. Clear frames on white also fail this, as their cut-out
# is patchy.
MIN_LENS_SYMMETRY = 0.85


class TryOnError(Exception):
    """A try-on could not be produced; the message is safe to show users."""


def garment_category(name):
    """Return "upper_body", "lower_body", "dresses" or None for a product name."""
    text = (name or "").lower()
    if not text or NOT_GARMENT.search(text):
        return None

    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", text))
    # Dresses first ("kurti dress" is a dress), then tops before bottoms, so
    # outfits like "kurti with palazzo" or "short kurti" try on the top.
    for category in ("dresses", "upper_body", "lower_body"):
        vocabulary = GARMENT_WORDS[category]
        if words & vocabulary or any(" " in v and v in text for v in vocabulary):
            return category
    return None


def accessory_category(name):
    """Return "glasses", "watch" or None: accessories tried on with the camera."""
    text = (name or "").lower()
    if not text or NOT_ACCESSORY.search(text):
        return None
    if GLASSES_PATTERN.search(text):
        return "glasses"
    if WATCH_PATTERN.search(text):
        return "watch"
    return None


# --------------------------------------------------
# Image preparation
# --------------------------------------------------


def fit_person(image):
    """Centre-crop the person photo to 3:4 and resize, without stretching."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    return ImageOps.fit(image, TRYON_SIZE, Image.LANCZOS, centering=(0.5, 0.4))


def fit_garment(image):
    """Pad the garment photo to 3:4 on white and resize, without cropping."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    return ImageOps.pad(image, TRYON_SIZE, Image.LANCZOS, color=(255, 255, 255))


def is_public_host(hostname):
    """Reject loopback, private and link-local addresses (no internal fetches)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False
    return True


def download_garment(url):
    """Download a product image from a public http(s) URL."""
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TryOnError("This product doesn't have a usable image.")
    if not is_public_host(parsed.hostname):
        raise TryOnError("This product image can't be used.")

    try:
        with requests.get(url, headers=REQUEST_HEADERS, timeout=15, stream=True) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > MAX_GARMENT_BYTES:
                    raise TryOnError("This product image is too large.")
        image = Image.open(io.BytesIO(content))
        image.load()
        return image
    except TryOnError:
        raise
    except Exception as exc:
        print(f"Could not load garment image {url}: {exc}")
        raise TryOnError("Couldn't load this product's image. Try another item.")


def _border_pixels(image):
    width, height = image.size
    pixels = image.load()
    step = max(1, min(width, height) // 60)
    points = [(x, y) for x in range(0, width, step) for y in (0, height - 1)]
    points += [(x, y) for y in range(0, height, step) for x in (0, width - 1)]
    return points, [pixels[point] for point in points]


def _unblend(rgb, mask, background):
    """
    RGBA from the photo and mask, with the background colour taken out of
    the soft edge pixels, so no white halo shows over a face or wrist.
    """
    colour = np.asarray(rgb).astype(np.float32)
    alpha = np.asarray(mask).astype(np.float32) / 255
    edge = (alpha > 0.04) & (alpha < 0.98)
    if edge.any():
        a = alpha[edge][:, None]
        colour[edge] = (colour[edge] - (1 - a) * np.array(background, np.float32)) / a
    pixels = np.dstack([np.clip(colour, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(pixels, "RGBA")


def _trim(rgba):
    box = rgba.getchannel("A").point(lambda value: 255 if value > 24 else 0).getbbox()
    if not box:
        raise TryOnError("Couldn't find the product in its photo. Try another listing.")
    return rgba.crop(box)


# Small gaps between the bridge bars sit in the middle of the frame; unlike
# reflections on mirrored lenses (which are inside a lens) they are background.
BRIDGE_ZONE = (0.38, 0.62)
MIN_BRIDGE_GAP_AREA = 0.001


def _clear_lenses(mask):
    """
    Mark enclosed background areas (value 0) as background (128): large ones
    (clear lenses) and any gap between the bridge bars. Small areas elsewhere
    stay, as they are reflections on mirrored lenses.
    """
    width, height = mask.size
    min_area = MIN_LENS_AREA * width * height
    min_gap = MIN_BRIDGE_GAP_AREA * width * height
    data = mask.load()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if data[x, y] != 0:
                continue
            ImageDraw.floodfill(mask, (x, y), 64)
            area = mask.histogram()[64]
            clear = area >= min_area
            if not clear and area >= min_gap:
                columns = np.nonzero((np.asarray(mask) == 64).any(axis=0))[0]
                centre = (columns.min() + columns.max() + 1) / 2 / width
                clear = BRIDGE_ZONE[0] <= centre <= BRIDGE_ZONE[1]
            ImageDraw.floodfill(mask, (x, y), 128 if clear else 255)


def cut_out_product(image, category):
    """
    Remove a plain (usually white) background from a product photo.

    Returns an RGBA image trimmed to the product. For glasses every
    background-coloured area becomes transparent, so clear lenses show the
    face behind them; for watches only background touching the edges does,
    so a white dial stays white. Raises TryOnError if the photo has no plain
    background (for example a model wearing the product).
    """
    image = ImageOps.exif_transpose(image)
    image.thumbnail((OVERLAY_MAX_SIZE, OVERLAY_MAX_SIZE), Image.LANCZOS)

    # Photos that are already cut out (transparent PNGs) keep their alpha.
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 128:
            return _trim(rgba)

    rgb = image.convert("RGB")
    points, colours = _border_pixels(rgb)
    # The most common border colour (rounded) is taken as the background.
    rounded = [tuple(channel // 8 * 8 + 4 for channel in colour) for colour in colours]
    background = max(set(rounded), key=rounded.count)

    def distance(colour):
        return max(abs(a - b) for a, b in zip(colour, background))

    plain = sum(distance(colour) <= BACKGROUND_TOLERANCE for colour in colours)
    if plain / len(colours) < MIN_PLAIN_BORDER:
        raise TryOnError(
            "This product photo doesn't have a plain background, so it can't be "
            "placed on you. Try another listing."
        )

    # Foreground = pixels that differ clearly from the background colour.
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    red, green, blue = difference.split()
    spread = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    mask = spread.point(lambda value: 255 if value > BACKGROUND_TOLERANCE else 0)

    # Background touching the edges is removed. Enclosed background areas
    # are removed too for glasses when large (clear lenses), but kept when
    # small (reflections on mirrored lenses) and always for watches (dials).
    for point in points:
        if mask.getpixel(point) == 0:
            ImageDraw.floodfill(mask, point, 128)
    if category == "glasses":
        _clear_lenses(mask)
    mask = mask.point(lambda value: 0 if value == 128 else 255)

    # Close pinholes, pull the edge in by a pixel (photos on white leave a
    # light rim around the product), then soften it to blend into video.
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))

    product = _trim(_unblend(rgb, mask, background))

    if category == "glasses" and product.width < product.height * MIN_GLASSES_RATIO:
        raise TryOnError(
            "This listing's photo isn't a front view of the glasses, so it can't be "
            "placed on you. Try another listing."
        )
    return product


NOT_FRONT_VIEW = (
    "This listing's photo isn't a clear front view of the glasses, so it can't "
    "be placed on you. Try another listing."
)


def lens_centres(product):
    """
    Find the centre of each lens in a glasses cut-out, as fractions of its
    width and height: (left_x, left_y, right_x, right_y).

    The bridge is the thinnest column in the middle; on each side, columns
    with at least half the most coverage are the lens (temple arms are thin
    and drop out). Raises TryOnError for photos that aren't a front view.
    """
    alpha = np.asarray(product.getchannel("A")) > 128
    height, width = alpha.shape
    columns = alpha.sum(axis=0).astype(float)

    low, high = int(width * 0.3), int(width * 0.7)
    if high <= low:
        raise TryOnError(NOT_FRONT_VIEW)
    bridge = low + int(np.argmin(columns[low:high]))

    lenses = []
    for start, end in ((0, bridge), (bridge + 1, width)):
        side = columns[start:end]
        if not side.size or side.max() == 0:
            raise TryOnError(NOT_FRONT_VIEW)
        is_lens = side >= side.max() * 0.5
        xs = np.arange(start, end)[is_lens]
        weights = side[is_lens]
        rows = np.nonzero(alpha[:, xs])[0]
        top, bottom = np.percentile(rows, [3, 97])
        lenses.append({
            "x": float((xs * weights).sum() / weights.sum()),
            "y": float(top + bottom) / 2,
            "width": float(xs.max() - xs.min() + 1),
            "height": float(bottom - top + 1),
        })

    left, right = lenses
    for key in ("width", "height"):
        if min(left[key], right[key]) / max(left[key], right[key]) < MIN_LENS_SYMMETRY:
            raise TryOnError(NOT_FRONT_VIEW)

    return (
        left["x"] / width,
        left["y"] / height,
        right["x"] / width,
        right["y"] / height,
    )


# Lens shape analysis runs on a small copy of the cut-out.
ANALYSIS_WIDTH = 240
MIN_LENS_AREA_SHARE = 0.02  # a lens covers at least this share of the photo
DARK_LENS_LUMA = 85  # tinted (sunglasses) lenses are darker than this


def _components(binary, max_regions=400):
    """Connected regions of a boolean array, largest first, as boolean masks."""
    # A copy: images made from numpy arrays can be read-only.
    image = Image.fromarray(binary.astype(np.uint8) * 255).copy()
    regions = []
    for _ in range(max_regions):
        remaining = np.nonzero(np.asarray(image) == 255)
        if not remaining[0].size:
            break
        seed = (int(remaining[1][0]), int(remaining[0][0]))
        ImageDraw.floodfill(image, seed, 128)
        regions.append(np.asarray(image) == 128)
        ImageDraw.floodfill(image, seed, 0)
    return sorted(regions, key=lambda region: -region.sum())


def _touches_border(region):
    return region[0].any() or region[-1].any() or region[:, 0].any() or region[:, -1].any()


def _box(region):
    ys, xs = np.nonzero(region)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def _solid_lens(region):
    """Close small gaps and fill holes (reflections) in a tinted lens area."""
    image = Image.fromarray(region.astype(np.uint8) * 255).copy()
    image = image.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    # A 1px empty border connects everything outside the lens.
    outside = ImageOps.expand(image, border=1, fill=0)
    ImageDraw.floodfill(outside, (0, 0), 128)
    return np.asarray(outside)[1:-1, 1:-1] != 128


def _lens_regions(product):
    """The two largest lens areas: holes (clear lenses) or dark areas (tinted)."""
    scale = min(1.0, ANALYSIS_WIDTH / product.width)
    small = product.resize(
        (max(1, round(product.width * scale)), max(1, round(product.height * scale))),
        Image.LANCZOS,
    )
    pixels = np.asarray(small).astype(float)
    opaque = pixels[..., 3] > 128
    min_area = MIN_LENS_AREA_SHARE * opaque.size

    holes = [
        region for region in _components(~opaque)
        if region.sum() >= min_area and not _touches_border(region)
    ]
    if holes:
        return holes[:2]

    luma = pixels[..., :3] @ np.array([0.299, 0.587, 0.114])
    levels = luma[opaque]
    if not levels.size:
        return []
    threshold = min(DARK_LENS_LUMA * 1.4, (np.percentile(levels, 10) + np.percentile(levels, 90)) / 2)
    dark = np.asarray(
        Image.fromarray((opaque & (luma < threshold)).astype(np.uint8) * 255).copy().filter(ImageFilter.MaxFilter(3))
    ) > 0
    lenses = [_solid_lens(region) & opaque for region in _components(dark) if region.sum() >= min_area * 0.6]
    return sorted((lens for lens in lenses if lens.sum() >= min_area), key=lambda lens: -lens.sum())[:2]


def front_lens_centres(product):
    """
    Lens centres (lx, ly, rx, ry as fractions of the photo) for a front-view
    glasses photo. Clear lenses are found as holes in the frame and tinted
    ones as dark areas; both lenses must look alike, which rules out angled
    photos. Falls back to lens_centres for frames neither method can read.
    Raises TryOnError when the photo isn't a front view.
    """
    lenses = _lens_regions(product)
    if len(lenses) == 2:
        boxes = sorted(_box(lens) for lens in lenses)
        (l1, t1, r1, b1), (l2, t2, r2, b2) = boxes
        sizes = [(r1 - l1, b1 - t1), (r2 - l2, b2 - t2)]
        if all(min(a, b) / max(a, b) >= MIN_LENS_SYMMETRY for a, b in zip(*sizes)):
            height, width = lenses[0].shape
            return (
                (l1 + r1) / 2 / width, (t1 + b1) / 2 / height,
                (l2 + r2) / 2 / width, (t2 + b2) / 2 / height,
            )
        raise TryOnError(NOT_FRONT_VIEW)
    return lens_centres(product)


TINTED_LENS_OPACITY = 0.8  # real sunglasses let a little of the eyes show


def soften_tinted_lenses(product):
    """Make dark lenses slightly see-through, so they look worn, not pasted."""
    alpha = np.asarray(product.getchannel("A")).astype(np.float32)
    lenses = _lens_regions(product)
    if not lenses:
        return product
    small_height, small_width = lenses[0].shape
    small_alpha = np.asarray(
        product.getchannel("A").resize((small_width, small_height), Image.BILINEAR)
    )
    tinted = np.zeros((small_height, small_width), dtype=bool)
    for lens in lenses:
        if small_alpha[lens].mean() > 128:  # opaque: a tinted lens, not a hole
            tinted |= lens
    if not tinted.any():
        return product
    lens_mask = Image.fromarray(tinted.astype(np.uint8) * 255).resize(product.size, Image.BILINEAR)
    lens_mask = lens_mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(2))
    weight = np.asarray(lens_mask).astype(np.float32) / 255
    alpha *= 1 - weight * (1 - TINTED_LENS_OPACITY)
    softened = product.copy()
    softened.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    return softened


def product_overlay(image_url, category):
    """
    Download a glasses or watch photo and return (PNG bytes, lens centres).
    Lens centres (see front_lens_centres) are None for watches.
    """
    if category not in ("glasses", "watch"):
        raise TryOnError("This item can't be tried on live.")

    cut_out = cut_out_product(download_garment(image_url), category)
    centres = front_lens_centres(cut_out) if category == "glasses" else None
    if category == "glasses":
        cut_out = soften_tinted_lenses(cut_out)
    output = io.BytesIO()
    cut_out.save(output, format="PNG", optimize=True)
    return output.getvalue(), centres


# --------------------------------------------------
# Models
# --------------------------------------------------


def _client(space):
    from gradio_client import Client  # imported lazily; only try-on needs it

    # HF_TOKEN in production; locally, fall back to the saved `hf auth login`.
    token = os.getenv("HF_TOKEN")
    if not token:
        from huggingface_hub import get_token

        token = get_token()
    return Client(space, token=token or None, verbose=False)


def _result_path(result):
    first = result[0] if isinstance(result, (list, tuple)) else result
    return first if isinstance(first, str) else (first or {}).get("path")


def run_leffa(person_path, garment_path, category):
    from gradio_client import handle_file

    # Leffa's VITON-HD model handles tops best; Dress Code covers the rest.
    model = "viton_hd" if category == "upper_body" else "dress_code"
    job = _client(LEFFA_SPACE).submit(
        src_image_path=handle_file(person_path),
        ref_image_path=handle_file(garment_path),
        ref_acceleration=False,
        step=30,
        scale=2.5,
        seed=42,
        vt_model_type=model,
        vt_garment_type=category,
        vt_repaint=False,
        api_name="/leffa_predict_vt",
    )
    return _result_path(job.result(timeout=MODEL_TIMEOUT_SECONDS))


def run_idm_vton(person_path, garment_path, description):
    from gradio_client import handle_file

    job = _client(IDM_SPACE).submit(
        dict={"background": handle_file(person_path), "layers": [], "composite": None},
        garm_img=handle_file(garment_path),
        garment_des=description[:120],
        is_checked=True,
        is_checked_crop=False,
        denoise_steps=30,
        seed=42,
        api_name="/tryon",
    )
    return _result_path(job.result(timeout=MODEL_TIMEOUT_SECONDS))


QUOTA_MESSAGE = (
    "Today's free try-on limit has been reached. It refills automatically, "
    "so please try again in a few hours."
)


def is_quota_error(exc):
    """Hugging Face's free GPU allowance (ZeroGPU quota) is used up."""
    text = str(exc).lower()
    return "zerogpu" in text and ("quota" in text or "limit" in text)


def try_on(person_image, garment_url, category, garment_name=""):
    """
    Render the person wearing the garment. Returns JPEG bytes.

    Raises TryOnError with a user-facing message if every model fails.
    """
    if category not in GARMENT_WORDS:
        raise TryOnError("This item can't be tried on.")

    garment_image = download_garment(garment_url)

    with tempfile.TemporaryDirectory() as folder:
        person_path = Path(folder) / "person.jpg"
        garment_path = Path(folder) / "garment.jpg"
        fit_person(person_image).save(person_path, quality=95)
        fit_garment(garment_image).save(garment_path, quality=95)

        attempts = [("Leffa", lambda: run_leffa(person_path, garment_path, category))]
        if category == "upper_body":
            attempts.append(
                ("IDM-VTON", lambda: run_idm_vton(person_path, garment_path, garment_name or "top"))
            )

        for model_name, attempt in attempts:
            try:
                result_path = attempt()
                if not result_path:
                    raise RuntimeError("no image returned")
                with Image.open(result_path) as result:
                    output = io.BytesIO()
                    result.convert("RGB").save(output, format="JPEG", quality=90)
                print(f"Try-on succeeded with {model_name}.")
                return output.getvalue()
            except Exception as exc:
                print(f"Try-on with {model_name} failed: {type(exc).__name__}: {exc}")
                # Every model shares the account's GPU allowance, so stop.
                if is_quota_error(exc):
                    raise TryOnError(QUOTA_MESSAGE)

    raise TryOnError(
        "The try-on service is busy right now. Please try again in a minute."
    )
