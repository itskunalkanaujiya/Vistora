from PIL import Image

import colour_match as c


def solid(rgb):
    return Image.new("RGB", (60, 60), rgb)


def test_a_photo_reads_as_its_main_colours():
    assert c.photo_colours(solid((230, 110, 20))) == {"orange"}
    assert c.photo_colours(solid((10, 10, 10))) == {"black"}


def test_only_the_middle_of_the_photo_counts():
    photo = solid((250, 250, 250))
    photo.paste(Image.new("RGB", (30, 36), (200, 20, 20)), (15, 12))  # the middle is red, the edges white

    assert "red" in c.photo_colours(photo)


def test_titles_naming_colours_that_are_not_in_the_photo_mismatch():
    photo = {"orange", "brown", "red"}
    assert c.colour_mismatch("Kids Green Cotton Frock", photo)
    assert not c.colour_mismatch("Orange Pattu Pavadai", photo)
    assert not c.colour_mismatch("Maroon Silk Frock", photo)  # maroon can read as red or brown


def test_neutral_multicolour_and_unknown_cases_never_mismatch():
    photo = {"orange"}
    assert not c.colour_mismatch("Black Sports Watch", photo)  # black and white variants are normal
    assert not c.colour_mismatch("Multicolour Frock", photo)
    assert not c.colour_mismatch("Frock with dupatta", photo)  # no colour named
    assert not c.colour_mismatch("Green Frock", set())  # the photo's colours are unknown
