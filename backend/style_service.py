"""
Personal styling: rate an outfit, and find the colours that suit someone.

Rate my outfit: a vision model scores the outfit in a photo, says what
works, and suggests two or three changes; each change is a product that is
then searched like a Find the outfit item, so every tip is shoppable.

Colours that suit you: from a selfie, a vision model reads the person's
colouring (undertone, contrast) and returns a palette in plain shopping
colour words ("olive", "rust", "navy") so results can be matched against
listing titles. The selfie isn't stored; the browser keeps only the palette.

Both use the same vision models as Find the outfit (Gemini, then Groq).
"""

import os
import re

from outfit_service import (
    GENDERS,
    OutfitError,
    _clean,
    _emitter,
    ask_vision,
    price_range,
    shop_items,
)

# Rating is judged by the strongest vision model available, thinking hard
# and given time: a rating has to be right, not instant. A model Google has
# retired or that is out of quota is skipped for the next one.
RATE_GEMINI_MODELS = [
    model for model in (os.getenv("RATE_MODEL"), "gemini-pro-latest", "gemini-3.8-flash") if model
]
# A model that hangs is given up on after this long, so the fallback (Groq)
# still answers in good time.
RATE_OPTIONS = {"effort": "medium", "max_tokens": 8000, "timeout": 30}

# How much each area counts towards the score: an area the photo shows only
# in part counts for less.
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.75, "low": 0.4}
MIN_EVIDENCE_CHARS = 12
# Footwear advice is dropped when the photo doesn't show the feet.
FOOTWEAR_WORDS = {
    "shoe", "shoes", "sneaker", "sneakers", "loafer", "loafers", "sandal", "sandals", "boot", "boots",
    "heel", "heels", "flat", "flats", "slipper", "slippers", "chappal", "chappals", "jutti", "juttis",
    "mojari", "mojaris", "footwear", "slides", "sliders", "oxford", "oxfords", "brogue", "brogues",
}

MAX_FIXES = 3
MAX_STRENGTHS = 3
MAX_BEST_COLOURS = 10
MAX_AVOID_COLOURS = 5
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
UNDERTONES = {"warm", "cool", "neutral", "olive"}

RATE_PROMPT = """You are a professional fashion stylist rating one outfit for an Indian shopping app.
Rate the outfit worn by the main person in the photo. Your rating must be provable from the photo: every claim has to be something a person looking at the same photo can check.

STEP 1 - OBSERVE. Before scoring, note exactly what is visible: each garment and accessory with its colour, pattern, fabric look and how it is worn (tucked, open, rolled, layered). Note what is NOT visible (cropped feet, hidden hands, no bag) and the photo quality.

STEP 2 - SCORE four areas from 1 to 10 (one decimal) using these checks, and quote what you saw as evidence:
- colours: count the colours besides neutrals (black, white, grey, beige, navy, denim). Is there a clear relationship (monochrome, analogous, complementary, neutrals plus one accent)? Do two saturated colours compete? Is there more than one bold pattern? Is the contrast between the top and the bottom deliberate?
- fit: judged on the garments only. Do the shoulder seams sit at the shoulder edge? Do sleeves and hems end at sensible points? Do trousers or skirts fall at a sensible length for the shoe or setting? Is there pulling or bunching, or is the looseness clearly deliberate? Are the proportions balanced (fitted with loose, or deliberately oversized)? Cropped, oversized, layered or draped shapes are normal fashion choices: score how well they work with the rest, never mark them down for being unusual.
- styling: do footwear and accessories match the formality of the clothes? Do metals and leathers coordinate? Is layering purposeful? Are the garments pressed and finished (tucked, buttoned, or deliberately open)?
- occasion: do all the pieces sit at the same formality? Does the outfit suit the visible setting? If the setting is unclear, say so and judge the outfit against itself.
Score bands: 9-10 deliberate and flawless on every check; 7-8 cohesive with one small issue; 5-6 acceptable but flat or with one clear issue; 3-4 several clear issues; 1-2 clashing or unfinished. An area whose evidence names a clear problem cannot score above 6.5; an area with no problem found cannot score below 7. Different outfits must get different scores.

HOW TO WRITE IT
- evidence: one or two sentences naming concrete visible details (item, colour, position), e.g. "Sky-blue shirt over white trousers; the two colours sit far apart in tone and the shirt is the only colour."
- reason: one sentence giving the styling principle that links that evidence to the score, e.g. "A single saturated colour on a neutral base reads as a deliberate accent."
- confidence: "high" when everything the area needs is visible, "medium" when part is hidden, "low" when most of it cannot be seen. If footwear, accessories or the lower half are not visible, write that in not_visible, do not score or praise what you cannot see, and lower the confidence of the areas it affects.
- Penalise only what you can identify with certainty. If you cannot tell what a visible item is (a belt or an undergarment, a tie or a scarf), describe it neutrally ("dark waistband") and give no penalty and no praise for it. Never describe clothing as "exposed" or "revealing".
- Never mention the weather, season, climate or temperature (for example "suited to warm weather"): a photo cannot show them.
- Banned: empty praise ("stylish", "looks great", "vibrant", "stands out"), and any guess about the weather, season, age, budget, personality, body, brand (unless a logo is clearly legible) or an occasion the photo does not show.
- Never judge the person's body, weight, face, skin or looks, and never treat a trend or personal style as a fault; judge only how well the pieces work together.

Return JSON only:
{
  "photo": {"shows": e.g. "waist-up, front view, indoors", "not_visible": ["footwear", ...] or [], "quality": "good" | "fair" | "poor"},
  "gender": "men" | "women" | "boys" | "girls" | "kids" | "unisex",
  "wearing": every visible item with colour and one visible detail, e.g. ["sky-blue linen shirt, sleeves rolled, top buttons open", "white trousers", "steel-strap watch on the left wrist"],
  "analysis": {
    "colours": {"score": number, "confidence": "high" | "medium" | "low", "evidence": string, "reason": string},
    "fit": {same fields},
    "styling": {same fields},
    "occasion": {same fields}
  },
  "verdict": one specific sentence under 25 words that names the main reason for the overall result,
  "summary": 3 or 4 plain sentences that explain the rating to the person: what works and why (naming the visible items), what holds it back and why, and what the photo could not show. Facts from the photo only; no numbers and no empty praise,
  "occasion": what the visible pieces suit in 2-4 words, or "unclear",
  "strengths": 2 or 3 short phrases, each naming a visible item and what it does, e.g. "rolled sleeves balance the long shirt length",
  "fixes": [
    {
      "type": the common shopping name of ONE item, e.g. "belt", "watch", "loafers",
      "improves": "colours" | "fit" | "styling" | "occasion",
      "advice": one sentence under 22 words that names what is visible now and the exact problem it solves,
      "description": a 4-9 word shopping search for exactly that item: colour, material, style, then the item,
      "price_range": [lowest, highest] sensible price in rupees at the same price level as the outfit
    }
  ]
}
FIX RULES
- 0 to 3 fixes, each tied to a real problem in the analysis: pick the lowest-scoring areas. If the outfit is already strong, give fewer fixes and say so in the verdict. Never invent a problem to fill the list.
- A fix is a NEW item to buy. Only advise on items you can see, or on an item the visible clothes clearly call for (for example a belt when the trousers have belt loops and no belt is visible). Never give advice about anything listed in not_visible.
- "type", "advice" and "description" must all be about the same item, and the advice must say why, using the visible evidence.
- Match the outfit's style and price level: everyday clothes get everyday prices, not designer or real gold.
PALETTE_RULE- If no person or outfit is visible, return {"analysis": {}, "fixes": []}."""

PALETTE_RULE = "- Their best colours are {colours}: when a fix has a colour choice, prefer one of these.\n"
SCORE_AREAS = ("colours", "fit", "styling", "occasion")

COLOUR_PROMPT = """You are a professional personal colour analyst for an Indian shopping app.
From the person's natural colouring in this selfie, find the clothing colours that suit them. Your answer must be provable from the photo: every claim has to be something a person looking at the same photo can check.

STEP 1 - OBSERVE, and quote what you see:
- photo: the lighting (daylight, warm indoor light, cool screen light, flash), any colour cast, filter, heavy makeup, or dyed-looking hair, and whether the face is clear. These change how colours read, so list every problem in "issues".
- skin: depth (light, medium, deep) and the undertone cue you can actually see (golden-yellow, pink-red, neutral, olive-green). Judge it from the cheeks and forehead away from shadows.
- hair: its colour, and whether it looks natural or dyed (visible roots, unnatural shade).
- eyes: their colour, if visible.
- contrast: how different the skin, hair and eyes are in lightness (low, medium, high).

STEP 2 - DECIDE the undertone (warm, cool, neutral, olive) and the seasonal type from those observations only. The season must agree with the undertone: spring and autumn types are warm, summer and winter types are cool, and "soft" or "neutral" types sit between. If the observations conflict, or the lighting is poor, give the closest match and lower the confidence. Never be more certain than the photo allows.

STEP 3 - CHOOSE colours. For every colour give one short reason that points at one of your observations (for example "echoes the golden cast in your skin" or "holds its own against your high contrast"). Use the clothing colour words shoppers type that appear in product names ("olive", "rust", "navy", "mustard", "emerald", "maroon", "teal", "cream"); no poetic names. The hex must really be that colour.

Return JSON only:
{
  "photo": {"quality": "good" | "fair" | "poor", "issues": ["warm indoor light", ...] or []},
  "observations": {
    "skin": {"finding": e.g. "medium depth, warm golden undertone", "evidence": what you see, e.g. "yellow-gold cast across the cheeks and forehead, no pink flush", "confidence": "high" | "medium" | "low"},
    "hair": {same fields},
    "eyes": {same fields},
    "contrast": {same fields}
  },
  "undertone": "warm" | "cool" | "neutral" | "olive",
  "undertone_confidence": "high" | "medium" | "low",
  "season": the seasonal colour type, e.g. "Deep Autumn", "Soft Summer", "Bright Winter", "Warm Spring",
  "summary": 3 or 4 plain sentences explaining why this type fits, naming the observations that led to it, and saying what the photo made hard to judge,
  "best": 8 to 10 colours, each {"name": one or two common shopping colour words, "hex": "#RRGGBB", "reason": one sentence under 18 words},
  "avoid": 3 to 5 colours that are less flattering, same fields
}
Rules:
- Talk only about colouring and colours. Never comment on attractiveness, age, ethnicity, weight or any feature other than colour, and never suggest changing skin colour.
- Guess nothing you cannot see: if the eyes are hidden, say so in that observation and give it "low" confidence rather than guessing.
- If no face is clearly visible, return {"best": []}."""


# A photo can't show the weather, so claims about it are guesses, not facts.
GUESS = (
    r"(?:\b(?:warm|hot|cold|cool|mild|humid|rainy)[- ]?(?:weather|days?|climates?)\b"
    r"|\b(?:summer|winter|monsoon|season\w*|climate|weather)\b)"
)
GUESS_PHRASE = re.compile(
    r"[,;]?\s*\b(?:well[- ])?(?:suited|suitable|perfect|ideal|great|good|made|meant|right)\s+for\b[^.;]*?"
    + GUESS
    + r"[^.;]*",
    re.IGNORECASE,
)
GUESS_WORD = re.compile(GUESS, re.IGNORECASE)


def _grounded(text):
    """text without claims about the weather or season, which a photo can't show."""
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if not GUESS_WORD.search(sentence):
            kept.append(sentence)
            continue
        # Cut the guess out of the sentence; keep what is left only if it
        # still says something on its own.
        cleaned = GUESS_PHRASE.sub("", sentence).strip(" ,;")
        if cleaned and not GUESS_WORD.search(cleaned) and len(cleaned.split()) >= 4:
            kept.append(cleaned)
    return " ".join(kept).strip()


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(high, max(low, number)), 1)


def _phrases(values, limit, length):
    phrases = []
    for value in values if isinstance(values, list) else []:
        text = _clean(value, length)
        if text and text not in phrases:
            phrases.append(text)
        if len(phrases) == limit:
            break
    return phrases


def _details(analysis):
    """The per-area analysis: {area: {"score", "confidence", "evidence", "reason"}}."""
    details = {}
    for area in SCORE_AREAS:
        raw = analysis.get(area) if isinstance(analysis, dict) else None
        if not isinstance(raw, dict):
            continue
        score = _number(raw.get("score"), 1, 10)
        if score is None:
            continue
        evidence = _grounded(_clean(raw.get("evidence"), 320))
        confidence = _clean(raw.get("confidence"), 10).lower()
        if confidence not in CONFIDENCE_WEIGHT:
            confidence = "medium"
        if len(evidence) < MIN_EVIDENCE_CHARS:
            # A score with nothing shown to back it counts for little.
            confidence = "low"
        details[area] = {
            "score": score,
            "confidence": confidence,
            "evidence": evidence,
            "reason": _grounded(_clean(raw.get("reason"), 240)),
        }
    return details


AREA_NAMES = {"colours": "colours", "fit": "fit", "styling": "styling", "occasion": "occasion"}


def _fallback_summary(details, not_visible):
    """An explanation built from the evidence, for when the model wrote none."""
    # Only areas with real evidence are quoted.
    shown = {area: d for area, d in details.items() if len(d["evidence"]) >= MIN_EVIDENCE_CHARS}
    ranked = sorted(shown.items(), key=lambda item: item[1]["score"], reverse=True)
    parts = []
    if not ranked:
        return ""
    best_area, best = ranked[0]
    if best["evidence"]:
        parts.append(f"The strongest area is {AREA_NAMES[best_area]}: {best['evidence'].rstrip('.')}.")
    worst_area, worst = ranked[-1]
    if worst_area != best_area and worst["evidence"]:
        parts.append(f"{AREA_NAMES[worst_area].capitalize()} holds it back most: {worst['evidence'].rstrip('.')}.")
    if not_visible:
        parts.append(f"The photo does not show: {', '.join(not_visible)}.")
    return " ".join(parts)


def _not_visible(answer):
    photo = answer.get("photo") if isinstance(answer.get("photo"), dict) else {}
    return _phrases(photo.get("not_visible"), 6, 40)


def _footwear_hidden(not_visible):
    hidden = " ".join(not_visible).lower()
    return any(word in hidden for word in ("foot", "feet", "shoe", "sneaker", "sandal", "boot", "legs"))


def read_rating(answer):
    """
    The model's rating as {"gender", "score", "scores", "details", "wearing",
    "verdict", "occasion", "strengths", "not_visible", "fixes"}. The score is
    the mean of the rubric scores, weighted by how much of each area the
    photo shows, which is steadier than asking for one number.
    """
    details = _details(answer.get("analysis"))
    if details:
        scores = {area: detail["score"] for area, detail in details.items()}
        weights = {area: CONFIDENCE_WEIGHT[detail["confidence"]] for area, detail in details.items()}
        score = round(sum(scores[a] * weights[a] for a in scores) / sum(weights.values()), 1)
    else:
        raw_scores = answer.get("scores") if isinstance(answer.get("scores"), dict) else {}
        scores = {
            area: value
            for area in SCORE_AREAS
            if (value := _number(raw_scores.get(area), 1, 10)) is not None
        }
        if len(scores) >= 2:
            score = round(sum(scores.values()) / len(scores), 1)
        else:
            score = _number(answer.get("score"), 0, 10)

    not_visible = _not_visible(answer)
    skip_footwear = _footwear_hidden(not_visible)
    gender = _clean(answer.get("gender"), 10).lower()
    fixes = []
    for raw in answer.get("fixes") or []:
        if not isinstance(raw, dict):
            continue
        item_type = _clean(raw.get("type"), 30).lower()
        description = _clean(raw.get("description"), 90)
        if not item_type or not description or any(fix["type"] == item_type for fix in fixes):
            continue
        if skip_footwear and FOOTWEAR_WORDS & set(re.findall(r"[a-z]+", f"{item_type} {description}".lower())):
            continue
        improves = _clean(raw.get("improves"), 10).lower()
        fixes.append({
            "id": f"fix-{len(fixes) + 1}",
            "type": item_type,
            "description": description,
            "reason": _grounded(_clean(raw.get("advice") or raw.get("reason") or raw.get("tip"), 160)),
            "improves": improves if improves in SCORE_AREAS else None,
            "price_range": price_range(raw.get("price_range")),
            "box": None,
        })
        if len(fixes) == MAX_FIXES:
            break
    return {
        "gender": gender if gender in GENDERS else "unisex",
        "score": score,
        "scores": scores,
        "details": details,
        "wearing": _phrases(answer.get("wearing"), 8, 90),
        "verdict": _grounded(_clean(answer.get("verdict"), 200)),
        "summary": _grounded(_clean(answer.get("summary"), 700)) or _fallback_summary(details, not_visible),
        "occasion": _clean(answer.get("occasion"), 40),
        "strengths": [text for text in map(_grounded, _phrases(answer.get("strengths"), MAX_STRENGTHS, 110)) if text],
        "not_visible": not_visible,
        "fixes": fixes,
    }


def rate_prompt(colours=None):
    """The rating prompt, preferring the person's best colours when known."""
    names = [_clean(colour, 24).lower() for colour in (colours or [])][:10]
    names = [name for name in names if name]
    rule = PALETTE_RULE.format(colours=", ".join(names)) if names else ""
    return RATE_PROMPT.replace("PALETTE_RULE", rule)


def rate_outfit(image, on_event=None, colours=None):
    """
    Rate the outfit in a photo and shop its suggested fixes. colours: the
    person's best colours ("Colours that suit you"), used for the fixes.

    Emits "rating" (score, rubric scores, verdict, strengths), then "items"
    and one "item" per fix like Find the outfit; each fix's listings are
    checked by the listing judge. Returns {"rating", "gender", "items"}.
    """
    answer, _, _, name = ask_vision(
        image,
        rate_prompt(colours),
        "Rate my outfit isn't set up on this server yet.",
        gemini_models=RATE_GEMINI_MODELS,
        **RATE_OPTIONS,
    )
    rating = read_rating(answer)
    if not rating["score"]:
        raise OutfitError("Couldn't see an outfit to rate. Try a clear photo of someone, ideally full length.")

    emit = _emitter(on_event)
    public = {
        key: rating[key]
        for key in ("score", "scores", "details", "wearing", "verdict", "summary", "occasion", "strengths", "not_visible")
    }
    public["personalised"] = bool(colours)
    emit("rating", {"rating": public})
    if not rating["fixes"]:
        return {"rating": public, "gender": rating["gender"], "items": [], "model": name}
    result = shop_items(rating["fixes"], rating["gender"], emit, judge=True)
    return {**result, "rating": public, "model": name}


def _colours(values, limit):
    colours = []
    for raw in values if isinstance(values, list) else []:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"), 24).lower()
        hex_value = _clean(raw.get("hex"), 7)
        if not name or not HEX_COLOUR.match(hex_value) or any(c["name"] == name for c in colours):
            continue
        colours.append({
            "name": name,
            "hex": hex_value.lower(),
            "reason": _clean(raw.get("reason"), 160),
        })
        if len(colours) == limit:
            break
    return colours


OBSERVATION_AREAS = (("skin", "Skin"), ("hair", "Hair"), ("eyes", "Eyes"), ("contrast", "Contrast"))
CONFIDENCE_ORDER = ("low", "medium", "high")
WARM_SEASONS = ("spring", "autumn")
COOL_SEASONS = ("summer", "winter")


def _confidence(value, default="medium"):
    value = _clean(value, 10).lower()
    return value if value in CONFIDENCE_ORDER else default


def _observations(raw):
    """What the model saw: [{"area", "label", "finding", "evidence", "confidence"}]."""
    raw = raw if isinstance(raw, dict) else {}
    seen = []
    for area, label in OBSERVATION_AREAS:
        item = raw.get(area)
        if not isinstance(item, dict):
            continue
        finding = _clean(item.get("finding"), 120)
        if not finding:
            continue
        evidence = _clean(item.get("evidence"), 220)
        confidence = _confidence(item.get("confidence"))
        if len(evidence) < MIN_EVIDENCE_CHARS:
            confidence = "low"  # a finding with nothing shown to back it
        seen.append({"area": area, "label": label, "finding": finding, "evidence": evidence, "confidence": confidence})
    return seen


def _season_agrees(undertone, season):
    """False when the season belongs to the opposite temperature of the undertone."""
    season = (season or "").lower()
    if undertone == "warm":
        return not any(word in season for word in COOL_SEASONS)
    if undertone == "cool":
        return not any(word in season for word in WARM_SEASONS)
    return True


def _lowest(*levels):
    return min(levels, key=CONFIDENCE_ORDER.index)


def _colour_summary(observations, season):
    """An explanation built from the observations, for when the model wrote none."""
    findings = [f"{o['label'].lower()}: {o['finding']}" for o in observations if o["confidence"] != "low"]
    if not findings:
        return ""
    lead = f"Your colouring reads as {season}. " if season else ""
    return f"{lead}What the photo shows: " + "; ".join(findings) + "."


def analyse_colours(image):
    """
    The colours that suit the person in a selfie: {"undertone", "season",
    "summary", "confidence", "observations", "photo_issues", "best": [{"name",
    "hex", "reason"}], "avoid": [...]}. Raises OutfitError.
    """
    answer, _, _, _ = ask_vision(
        image,
        COLOUR_PROMPT,
        "Colour analysis isn't set up on this server yet.",
        gemini_models=RATE_GEMINI_MODELS,
        **RATE_OPTIONS,
    )
    best = _colours(answer.get("best"), MAX_BEST_COLOURS)
    if len(best) < 3:
        raise OutfitError("Couldn't see a face clearly. Try a front-facing selfie in daylight, without filters.")

    undertone = _clean(answer.get("undertone"), 10).lower()
    undertone = undertone if undertone in UNDERTONES else None
    season = _clean(answer.get("season"), 30)
    undertone_confidence = _confidence(answer.get("undertone_confidence"))
    if undertone and not _season_agrees(undertone, season):
        # An undertone and a season of opposite temperature can't both be right.
        undertone_confidence = "low"

    observations = _observations(answer.get("observations"))
    photo = answer.get("photo") if isinstance(answer.get("photo"), dict) else {}
    issues = _phrases(photo.get("issues"), 5, 60)
    quality = _clean(photo.get("quality"), 8).lower()

    # No more certain than the weakest of the undertone, the skin reading and the photo.
    confidence = _lowest(undertone_confidence, *[o["confidence"] for o in observations if o["area"] == "skin"])
    if quality == "poor":
        confidence = "low"
    elif issues:
        confidence = _lowest(confidence, "medium")

    return {
        "undertone": undertone,
        "undertone_confidence": undertone_confidence,
        "season": season,
        "summary": _clean(answer.get("summary"), 600) or _colour_summary(observations, season),
        "confidence": confidence,
        "observations": observations,
        "photo_issues": issues,
        "best": best,
        "avoid": _colours(answer.get("avoid"), MAX_AVOID_COLOURS),
    }
