import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
import outfit_service as o
import style_service as st
from conftest import FakeResponse

RATING = {
    "gender": "women",
    "score": 8.46,
    "wearing": ["maroon heart print shirt", "red leather skirt"],
    "verdict": "A bold, playful look.",
    "occasion": "casual day out",
    "strengths": ["bold print", "bold print", "great colours", "good fit", "extra"],
    "fixes": [
        {"type": "boots", "advice": "Add red ankle boots to match the skirt.", "description": "red leather ankle boots"},
        {"type": "boots", "advice": "Or black boots.", "description": "black ankle boots"},
        {"type": "scarf", "advice": "A black silk scarf ties it together.", "description": "black silk square scarf"},
        {"type": "", "description": "nothing"},
    ],
}

PALETTE = {
    "undertone": "Warm",
    "season": "Deep Autumn",
    "summary": "Rich, earthy colours match your contrast.",
    "best": [
        {"name": "Maroon", "hex": "#800000"},
        {"name": "olive", "hex": "#556B2F"},
        {"name": "olive", "hex": "#556b2f"},
        {"name": "mustard", "hex": "ffdb58"},
        {"name": "rust", "hex": "#b7410e"},
    ],
    "avoid": [{"name": "neon pink", "hex": "#ff10f0"}],
}


def reply(data):
    return FakeResponse(data={"choices": [{"message": {"content": json.dumps(data)}}]})


@pytest.fixture
def model(monkeypatch):
    state = {"answer": RATING, "sent": []}

    def post(url, headers, json, timeout):
        state["sent"].append(json)
        return reply(state["answer"])

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(o.requests, "post", post)
    monkeypatch.setattr(o, "search_products_by_text", lambda q, n, understand, min_relevance=None: {
        "best_matches": [{"name": f"{q} listing", "price": 999}], "cheapest_alternatives": []})
    return state


def test_rating_is_read_and_fixes_are_shopped(model):
    events = []
    result = st.rate_outfit(Image.new("RGB", (600, 800)), on_event=lambda kind, data: events.append((kind, data)))

    assert events[0] == ("rating", {"rating": {
        "score": 8.5,  # no rubric scores: the overall score is used
        "scores": {},
        "details": {},
        "wearing": ["maroon heart print shirt", "red leather skirt"],
        "verdict": "A bold, playful look.",
        "summary": "",
        "occasion": "casual day out",
        "strengths": ["bold print", "great colours", "good fit"],
        "not_visible": [],
        "personalised": False,
    }})
    assert [kind for kind, _ in events[1:]] == ["items", "item", "item"]
    assert [item["type"] for item in result["items"]] == ["boots", "scarf"]  # one per type
    assert result["items"][0]["reason"] == "Add red ankle boots to match the skirt."
    assert result["items"][0]["query"] == "women red leather ankle boots"
    assert result["rating"]["score"] == 8.5
    prompt = model["sent"][0]["messages"][0]["content"][0]["text"]
    assert "Never judge the person's body" in prompt


def test_no_outfit_to_rate(model):
    model["answer"] = {"score": 0, "fixes": []}
    with pytest.raises(o.OutfitError, match="Couldn't see an outfit"):
        st.rate_outfit(Image.new("RGB", (100, 100)))


def test_a_rating_without_fixes_still_returns(model):
    model["answer"] = {**RATING, "fixes": []}
    result = st.rate_outfit(Image.new("RGB", (100, 100)))
    assert result["items"] == [] and result["rating"]["score"] == 8.5


def test_colour_palette_is_cleaned(model):
    model["answer"] = PALETTE
    palette = st.analyse_colours(Image.new("RGB", (400, 400)))

    assert palette["undertone"] == "warm" and palette["season"] == "Deep Autumn"
    # Repeats and invalid hex codes are dropped; names are lower case.
    assert palette["best"] == [
        {"name": "maroon", "hex": "#800000", "reason": ""},
        {"name": "olive", "hex": "#556b2f", "reason": ""},
        {"name": "rust", "hex": "#b7410e", "reason": ""},
    ]
    assert palette["avoid"] == [{"name": "neon pink", "hex": "#ff10f0", "reason": ""}]
    prompt = model["sent"][0]["messages"][0]["content"][0]["text"]
    assert "never suggest changing skin colour" in prompt


def test_no_face_for_colours(model):
    model["answer"] = {"best": []}
    with pytest.raises(o.OutfitError, match="selfie"):
        st.analyse_colours(Image.new("RGB", (100, 100)))


def test_rate_endpoint_streams_rating_then_items(model, png_bytes):
    response = TestClient(main.app).post(
        "/api/v1/style/rate/stream", files={"file": ("me.png", png_bytes("blue"), "image/png")}
    )
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert [e["type"] for e in events] == ["stage", "rating", "items", "item", "item", "final"]
    assert events[-1]["rating"]["score"] == 8.5 and len(events[-1]["items"]) == 2


def test_colours_endpoint(model, png_bytes):
    model["answer"] = PALETTE
    client = TestClient(main.app)

    response = client.post("/api/v1/style/colours", files={"file": ("me.png", png_bytes("tan"), "image/png")})
    assert response.status_code == 200 and response.json()["season"] == "Deep Autumn"

    model["answer"] = {"best": []}
    failed = client.post("/api/v1/style/colours", files={"file": ("me.png", png_bytes("tan"), "image/png")})
    assert failed.status_code == 422 and "selfie" in failed.json()["detail"]


def test_colours_without_a_key(png_bytes):
    response = TestClient(main.app).post(
        "/api/v1/style/colours", files={"file": ("me.png", png_bytes("tan"), "image/png")}
    )
    assert response.status_code == 422 and "isn't set up" in response.json()["detail"]


def test_score_is_the_mean_of_the_rubric(model):
    model["answer"] = {**RATING, "scores": {"colours": 8, "fit": 7, "styling": 5.5, "occasion": 7.5, "vibe": 10}}
    result = st.rate_outfit(Image.new("RGB", (100, 100)))
    assert result["rating"]["score"] == 7.0
    assert result["rating"]["scores"] == {"colours": 8.0, "fit": 7.0, "styling": 5.5, "occasion": 7.5}


def test_fixes_keep_their_price_range(model):
    model["answer"] = {**RATING, "fixes": [
        {"type": "belt", "advice": "Add a belt.", "description": "black leather belt", "price_range": [1500, 400]},
        {"type": "watch", "advice": "Add a watch.", "description": "silver watch", "price_range": "cheap"},
    ]}
    result = st.rate_outfit(Image.new("RGB", (100, 100)))
    assert [item["price_range"] for item in result["items"]] == [[400, 1500], None]


def test_best_colours_go_into_the_prompt(model):
    st.rate_outfit(Image.new("RGB", (100, 100)), colours=["Maroon", "olive", ""])
    prompt = model["sent"][0]["messages"][0]["content"][0]["text"]
    assert "Their best colours are maroon, olive" in prompt
    assert "PALETTE_RULE" not in prompt

    model["sent"].clear()
    st.rate_outfit(Image.new("RGB", (100, 100)))
    assert "best colours" not in model["sent"][0]["messages"][0]["content"][0]["text"]


def test_rate_endpoint_passes_colours(model, png_bytes, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "rate_outfit", lambda image, on_event, colours: seen.append(colours) or {
        "rating": {"score": 7}, "gender": "women", "items": []})
    TestClient(main.app).post(
        "/api/v1/style/rate/stream",
        files={"file": ("me.png", png_bytes("blue"), "image/png")},
        data={"colours": "maroon, olive ,"},
    )
    assert seen == [["maroon", "olive"]]


EVIDENCE_RATING = {
    "photo": {"shows": "waist-up, front view", "not_visible": ["footwear", "bag"], "quality": "good"},
    "gender": "men",
    "wearing": ["sky-blue linen shirt, sleeves rolled", "white trousers"],
    "analysis": {
        "colours": {"score": 8.5, "confidence": "high",
                    "evidence": "Sky-blue shirt over white trousers; blue is the only colour.",
                    "reason": "One colour on a neutral base reads as deliberate."},
        "fit": {"score": 7, "confidence": "medium",
                "evidence": "Shirt hangs loose past the hips; trouser hem not visible.",
                "reason": "A relaxed shirt works, but the lower half is cropped."},
        "styling": {"score": 6, "confidence": "low", "evidence": "n/a", "reason": "Little is shown."},
        "occasion": {"score": 8, "confidence": "high",
                     "evidence": "Linen shirt and trousers share a relaxed formality.",
                     "reason": "Matching formality makes the look coherent."},
    },
    "verdict": "A clean, single-colour look.",
    "summary": "The blue shirt on white trousers is a clear, deliberate palette. The photo cuts off the feet.",
    "occasion": "casual day out",
    "strengths": ["rolled sleeves balance the long shirt"],
    "fixes": [
        {"type": "sneakers", "improves": "styling", "advice": "Add white sneakers.", "description": "white leather sneakers"},
        {"type": "watch", "improves": "styling", "advice": "Add a leather-strap watch.", "description": "brown leather strap watch"},
    ],
}


def test_rating_keeps_evidence_and_weights_by_visibility():
    rating = st.read_rating(EVIDENCE_RATING)

    detail = rating["details"]["colours"]
    assert detail["evidence"].startswith("Sky-blue shirt") and detail["confidence"] == "high"
    # "n/a" is not evidence, so that area counts as low confidence.
    assert rating["details"]["styling"]["confidence"] == "low"
    # Weighted mean: (8.5*1 + 7*.75 + 6*.4 + 8*1) / (1 + .75 + .4 + 1) = 7.67
    assert rating["score"] == 7.7
    assert rating["scores"] == {"colours": 8.5, "fit": 7.0, "styling": 6.0, "occasion": 8.0}
    assert rating["summary"].startswith("The blue shirt")
    assert rating["not_visible"] == ["footwear", "bag"]


def test_footwear_advice_is_dropped_when_the_feet_are_not_visible():
    rating = st.read_rating(EVIDENCE_RATING)

    assert [fix["type"] for fix in rating["fixes"]] == ["watch"]
    assert rating["fixes"][0]["improves"] == "styling"


def test_footwear_advice_is_kept_when_the_feet_are_visible():
    answer = {**EVIDENCE_RATING, "photo": {"not_visible": ["bag"]}}

    assert [fix["type"] for fix in st.read_rating(answer)["fixes"]] == ["sneakers", "watch"]


def test_the_rating_prompt_demands_evidence():
    prompt = st.rate_prompt(None)

    assert "OBSERVE" in prompt and "evidence" in prompt and "not_visible" in prompt
    assert "empty praise" in prompt


def test_rating_uses_the_strongest_models_and_a_long_timeout(model, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "")
    urls = []

    def post(url, headers, json, timeout):
        urls.append((json["model"], json.get("reasoning_effort"), timeout))
        return reply(RATING)

    monkeypatch.setattr(o.requests, "post", post)
    st.rate_outfit(Image.new("RGB", (100, 100)))

    assert urls[0][0] == "gemini-pro-latest" and urls[0][1] == "medium" and urls[0][2] == 30


def test_a_busy_rating_model_falls_through_to_the_next(model, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "")
    tried = []

    def post(url, headers, json, timeout):
        tried.append(json["model"])
        return FakeResponse(data={}, status_code=429) if json["model"] == "gemini-pro-latest" else reply(RATING)

    monkeypatch.setattr(o.requests, "post", post)
    result = st.rate_outfit(Image.new("RGB", (100, 100)))

    assert tried[:2] == ["gemini-pro-latest", "gemini-3.8-flash"] and result["rating"]["score"] == 8.5


def test_weather_and_season_guesses_are_removed():
    assert st._grounded("Lightweight blue shirt and white trousers suitable for warm weather casual wear.") == (
        "Lightweight blue shirt and white trousers."
    )
    assert st._grounded("The shirt pops. It is well-suited for summer. The trousers are plain.") == (
        "The shirt pops. The trousers are plain."
    )
    assert st._grounded("A crisp contrast, ideal for hot weather") == ""  # too little left to keep
    # Colour words that merely sound similar are left alone.
    assert st._grounded("Warm rust tones against cool navy.") == "Warm rust tones against cool navy."


def test_rating_text_never_keeps_weather_guesses():
    answer = {
        **EVIDENCE_RATING,
        "summary": "A clear palette. Great for warm weather.",
        "strengths": ["blue shirt keeps cool in summer", "rolled sleeves balance the length"],
    }
    rating = st.read_rating(answer)

    assert rating["summary"] == "A clear palette."
    assert rating["strengths"] == ["rolled sleeves balance the length"]


def test_an_explanation_is_built_from_the_evidence_when_the_model_writes_none():
    answer = {**EVIDENCE_RATING, "summary": ""}
    summary = st.read_rating(answer)["summary"]

    assert "strongest area is colours: Sky-blue shirt over white trousers" in summary
    assert "Styling holds it back most" not in summary  # "n/a" evidence is not quoted
    assert "does not show: footwear, bag" in summary


def test_the_prompt_does_not_punish_deliberate_shapes():
    assert "never mark them down for being unusual" in st.rate_prompt(None)


def test_the_prompt_does_not_penalise_what_it_cannot_identify():
    assert "Penalise only what you can identify with certainty" in st.rate_prompt(None)


EVIDENCE_PALETTE = {
    "photo": {"quality": "good", "issues": []},
    "observations": {
        "skin": {"finding": "medium depth, warm golden undertone",
                 "evidence": "Yellow-gold cast across the cheeks and forehead, no pink flush.", "confidence": "high"},
        "hair": {"finding": "dark brown", "evidence": "Even dark brown, no visible roots.", "confidence": "high"},
        "eyes": {"finding": "dark brown", "evidence": "n/a", "confidence": "high"},
        "contrast": {"finding": "medium-high", "evidence": "Dark hair against medium skin.", "confidence": "medium"},
    },
    "undertone": "warm",
    "undertone_confidence": "high",
    "season": "Deep Autumn",
    "summary": "The golden cast in your skin and the dark hair point to Deep Autumn.",
    "best": [
        {"name": "Rust", "hex": "#b7410e", "reason": "echoes the golden cast in your skin"},
        {"name": "olive", "hex": "#556b2f", "reason": "sits well with warm skin"},
        {"name": "mustard", "hex": "#e1ad01", "reason": "lifts warm undertones"},
    ],
    "avoid": [{"name": "icy pink", "hex": "#f8c8dc", "reason": "can wash out warm skin"}],
}


def test_colour_analysis_keeps_the_evidence_and_the_reasons(model):
    model["answer"] = EVIDENCE_PALETTE
    result = st.analyse_colours(Image.new("RGB", (400, 400)))

    assert [o["area"] for o in result["observations"]] == ["skin", "hair", "eyes", "contrast"]
    assert result["observations"][0]["evidence"].startswith("Yellow-gold cast")
    assert result["observations"][2]["confidence"] == "low"  # "n/a" is not evidence
    assert result["best"][0] == {"name": "rust", "hex": "#b7410e", "reason": "echoes the golden cast in your skin"}
    assert result["confidence"] == "high" and result["photo_issues"] == []


def test_a_season_of_the_opposite_temperature_lowers_confidence(model):
    model["answer"] = {**EVIDENCE_PALETTE, "season": "Cool Summer"}
    result = st.analyse_colours(Image.new("RGB", (400, 400)))

    assert result["undertone_confidence"] == "low" and result["confidence"] == "low"


def test_photo_problems_cap_the_confidence(model):
    model["answer"] = {**EVIDENCE_PALETTE, "photo": {"quality": "fair", "issues": ["warm indoor light", "filter"]}}
    result = st.analyse_colours(Image.new("RGB", (400, 400)))

    assert result["confidence"] == "medium" and result["photo_issues"] == ["warm indoor light", "filter"]

    model["answer"] = {**EVIDENCE_PALETTE, "photo": {"quality": "poor", "issues": []}}
    assert st.analyse_colours(Image.new("RGB", (400, 400)))["confidence"] == "low"


def test_colour_summary_is_built_from_the_observations_when_missing(model):
    model["answer"] = {**EVIDENCE_PALETTE, "summary": ""}
    summary = st.analyse_colours(Image.new("RGB", (400, 400)))["summary"]

    assert summary.startswith("Your colouring reads as Deep Autumn.")
    assert "skin: medium depth, warm golden undertone" in summary
    assert "eyes" not in summary  # low confidence findings are not quoted


def test_colour_prompt_demands_evidence_and_the_best_model(model, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "")
    seen = []

    def post(url, headers, json, timeout):
        seen.append((json["model"], timeout, json["messages"][0]["content"][0]["text"]))
        return reply(EVIDENCE_PALETTE)

    monkeypatch.setattr(o.requests, "post", post)
    st.analyse_colours(Image.new("RGB", (400, 400)))

    model_name, timeout, prompt = seen[0]
    assert model_name == "gemini-pro-latest" and timeout == 30
    assert "OBSERVE" in prompt and "provable from the photo" in prompt
    assert "Never be more certain than the photo allows" in prompt
    assert "never suggest changing skin colour" in prompt
