import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import main
import tryon_service as t

OVERLAY = "/api/v1/tryon/overlay"
IMAGE_URL = "https://encrypted-tbn0.gstatic.com/images?q=sunglasses"


@pytest.mark.parametrize(
    "name, category",
    [
        ("Fastrack UV Protected Aviator Sunglasses for Men", "glasses"),
        ("Ray-Ban RB3025 Unisex Sun Glasses", "glasses"),
        ("Lenskart Blu Computer Glasses Blue Light", "glasses"),
        ("Vincent Chase Eyeglasses Rectangular Frames", "glasses"),
        ("Casio G-Shock GA-2100 Analog-Digital Watch", "watch"),
        ("Noise ColorFit Pro 5 Smartwatch", "watch"),
        ("Men Silver Watch with Stainless Steel Band", "watch"),
        ("Borosil Wine Glasses Set of 6", None),
        ("Swimming Goggles Anti Fog", None),
        ("Silicone Watch Strap 22mm", None),
        ("Smart Watch Band for ColorFit", None),
        ("Sunglasses Chain for Women", None),
        ("Watch Box Organiser", None),
        ("Men Shirt with Watch Print", None),
        ("Levi's Slim Fit Jeans", None),
        ("", None),
    ],
)
def test_accessory_category(name, category):
    assert t.accessory_category(name) == category


def glasses_photo(lens="white"):
    """Two lens rims and a bridge on white; `lens` fills the lenses."""
    image = Image.new("RGB", (300, 120), "white")
    draw = ImageDraw.Draw(image)
    for left in (30, 160):
        draw.ellipse((left, 20, left + 110, 100), fill=lens, outline="black", width=6)
    draw.line((140, 50, 160, 50), fill="black", width=6)
    return image


def alpha_at(image, point):
    return image.getchannel("A").getpixel(point)


def test_glasses_cut_out_removes_background_and_clear_lenses():
    cut = t.cut_out_product(glasses_photo(lens="white"), "glasses")

    # Trimmed to the frame, with transparent corners and lens centres.
    assert cut.width < 300 and cut.height < 120
    assert alpha_at(cut, (0, 0)) == 0
    assert alpha_at(cut, (cut.width // 4, cut.height // 2)) == 0
    # The rim stays solid.
    assert alpha_at(cut, (cut.width // 4, 2)) > 200


def test_glasses_cut_out_keeps_tinted_lenses():
    cut = t.cut_out_product(glasses_photo(lens=(40, 40, 40)), "glasses")
    assert alpha_at(cut, (cut.width // 4, cut.height // 2)) == 255


def test_watch_cut_out_keeps_a_white_dial():
    image = Image.new("RGB", (200, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 10, 120, 290), fill="brown")  # strap
    draw.ellipse((50, 100, 150, 200), fill="white", outline="silver", width=8)  # case

    cut = t.cut_out_product(image, "watch")

    assert alpha_at(cut, (0, 0)) == 0
    assert alpha_at(cut, (cut.width // 2, cut.height // 2)) == 255  # dial


def test_photos_without_plain_background_are_refused():
    noisy = Image.effect_noise((200, 200), 100).convert("RGB")
    with pytest.raises(t.TryOnError):
        t.cut_out_product(noisy, "watch")


def test_tall_glasses_photos_are_refused():
    # A tall cut-out is a model wearing the glasses, not a front view.
    image = Image.new("RGB", (200, 300), "white")
    ImageDraw.Draw(image).rectangle((40, 30, 160, 270), fill="tan")
    with pytest.raises(t.TryOnError):
        t.cut_out_product(image, "glasses")


def test_transparent_pngs_keep_their_alpha():
    image = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 30, 180, 70), fill=(200, 0, 0, 255))
    cut = t.cut_out_product(image, "glasses")
    assert cut.size == (161, 41)


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def fake_download(monkeypatch):
    calls = []

    def download(url):
        calls.append(url)
        return glasses_photo(lens=(40, 40, 40))

    monkeypatch.setattr(t, "download_garment", download)
    return calls


def test_overlay_endpoint_returns_a_png_and_caches(client, fake_download):
    first = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "glasses"})
    second = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "glasses"})

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(first.content)).mode == "RGBA"
    assert len(fake_download) == 1


def test_overlay_rejects_unknown_categories(client, fake_download):
    response = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "upper_body"})
    assert response.status_code == 400
    assert fake_download == []


def test_overlay_reports_unusable_photos(client, monkeypatch):
    def download(url):
        return Image.effect_noise((200, 200), 100).convert("RGB")

    monkeypatch.setattr(t, "download_garment", download)
    response = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "watch"})
    assert response.status_code == 422
    assert "plain background" in response.json()["detail"]


def test_overlay_has_a_limit(client, fake_download, monkeypatch):
    monkeypatch.setattr(main, "OVERLAY_LIMIT", 1)
    assert client.get(OVERLAY, params={"url": IMAGE_URL, "category": "glasses"}).status_code == 200
    other = client.get(OVERLAY, params={"url": IMAGE_URL + "2", "category": "glasses"})
    assert other.status_code == 429


def test_lens_centres_of_a_front_view():
    cut = t.cut_out_product(glasses_photo(lens=(40, 40, 40)), "glasses")
    left_x, left_y, right_x, right_y = t.lens_centres(cut)

    assert 0.15 < left_x < 0.3 and 0.7 < right_x < 0.85
    assert abs(left_y - 0.5) < 0.05 and abs(right_y - 0.5) < 0.05


def test_angled_glasses_photos_are_refused():
    # The far lens looks much narrower in an angled view.
    image = Image.new("RGB", (300, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 15, 150, 105), fill=(40, 40, 40))
    draw.ellipse((190, 30, 240, 90), fill=(40, 40, 40))
    draw.line((150, 50, 190, 50), fill="black", width=6)
    cut = t.cut_out_product(image, "glasses")

    with pytest.raises(t.TryOnError):
        t.lens_centres(cut)


def test_overlay_sends_lens_centres_and_caches_refusals(client, monkeypatch):
    calls = []

    def download(url):
        calls.append(url)
        return Image.effect_noise((200, 200), 100).convert("RGB") if "bad" in url else glasses_photo((40, 40, 40))

    monkeypatch.setattr(t, "download_garment", download)
    good = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "glasses"})
    assert len(good.headers["x-lens-centres"].split(",")) == 4

    for _ in range(2):
        bad = client.get(OVERLAY, params={"url": IMAGE_URL + "bad", "category": "glasses"})
        assert bad.status_code == 422
    assert len(calls) == 2


def rim_glasses(left_width, right_width, colour="royalblue"):
    """Clear-lens glasses: two rims of the given widths on white."""
    image = Image.new("RGB", (320, 130), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 25, 20 + left_width, 105), radius=25, outline=colour, width=9)
    right = 300 - right_width
    draw.rounded_rectangle((right, 25 + (120 - right_width) // 6, 300, 105 - (120 - right_width) // 6), radius=20, outline=colour, width=9)
    draw.line((20 + left_width, 50, right, 50), fill=colour, width=7)
    return image


def test_front_view_clear_glasses_give_lens_centres():
    cut = t.cut_out_product(rim_glasses(120, 120), "glasses")
    left_x, left_y, right_x, right_y = t.front_lens_centres(cut)

    assert left_x < 0.4 < 0.6 < right_x
    assert abs(left_y - right_y) < 0.05


def test_angled_clear_glasses_are_refused():
    # The far lens is much narrower, as in an angled catalogue photo.
    cut = t.cut_out_product(rim_glasses(140, 70), "glasses")
    with pytest.raises(t.TryOnError):
        t.front_lens_centres(cut)


def test_overlay_refuses_angled_glasses(client, monkeypatch):
    monkeypatch.setattr(t, "download_garment", lambda url: rim_glasses(140, 70))
    response = client.get(OVERLAY, params={"url": IMAGE_URL, "category": "glasses"})
    assert response.status_code == 422
    assert "front view" in response.json()["detail"]


def bridge_gap_photo(lens="black"):
    """Tinted lenses joined by a brow bar, with a small white gap between the bars."""
    image = Image.new("RGB", (300, 120), "white")
    draw = ImageDraw.Draw(image)
    for left in (30, 160):
        draw.ellipse((left, 20, left + 110, 100), fill=lens, outline="black", width=4)
    draw.rectangle((120, 20, 180, 28), fill="black")  # the brow bar
    draw.rectangle((138, 28, 162, 62), fill="black")  # bridge arch, with a gap under the bar
    draw.rectangle((144, 31, 156, 38), fill="white")  # the gap: background seen between the bars
    return image


def test_the_gap_between_the_bridge_bars_is_cut_out():
    cut = t.cut_out_product(bridge_gap_photo(), "glasses")
    centre = cut.width // 2
    # The gap is 7 px tall, starting 11 px below the top of the trimmed frame.
    inside_gap = [alpha_at(cut, (centre, y)) for y in range(13, 16)]
    assert max(inside_gap) == 0, "the gap between the bridge bars should be transparent"
    assert alpha_at(cut, (centre, 22)) > 200  # the bridge arch below it stays solid
    assert alpha_at(cut, (cut.width // 4, cut.height // 2)) > 200  # the tinted lens stays solid


def test_small_reflections_inside_a_lens_are_kept():
    image = bridge_gap_photo()
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 40, 75, 52), fill="white")  # a glare spot inside the left lens
    cut = t.cut_out_product(image, "glasses")
    left_lens_glare = (55 - 30 + 10, 40 - 20 + 6)
    assert alpha_at(cut, left_lens_glare) > 128
