"""
Read a shopping request with a language model (Groq's free tier).

The rule-based reader in query_understanding.py handles specs written as
numbers and units. The model adds understanding of looser phrasing:
"a phone that's good for gaming and lasts all day under 20k" becomes a
gaming phone with a big battery and a ₹20,000 budget, and "something to
keep my tea hot at work" becomes an insulated flask.

The model (Qwen3.8 27B on Groq) only runs for sentence-like requests (short keyword searches
don't need it), answers in strict JSON, and anything unexpected falls back
to the rule-based reader.
"""

import json
import os
import re
import threading
from collections import OrderedDict

import requests

from http_session import reliable_session
from query_understanding import (
    AUDIENCE,
    COLOURS,
    FILLER_WORDS,
    SPEC_FORMAT,
    ParsedQuery,
    Spec,
    parse_query,
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Tried in order; a retired model (Groq retires them now and then) is skipped.
# Qwen gave the cleanest search queries in our tests, at about 0.7 s.
GROQ_MODELS = [
    model
    for model in (os.getenv("GROQ_MODEL"), "qwen/qwen3.8-27b", "openai/gpt-oss-20b")
    if model
]
_retired_models = set()
TIMEOUT_SECONDS = 4
CACHE_ENTRIES = 500

# Spec fields the model may return, mapped to query_understanding spec kinds.
SPEC_FIELDS = {
    "ram_gb": "ram",
    "storage_gb": "storage",
    "screen_inches": "screen",
    "battery_mah": "battery",
    "camera_mp": "camera",
    "refresh_hz": "refresh",
    "power_watts": "power",
    "capacity_litres": "volume",
    "weight_kg": "weight",
    "ac_tons": "tonnage",
}

SYSTEM_PROMPT = """You read shopping requests from customers in India and return JSON only.

Return exactly these keys:
{
  "product": short product type in plain words, e.g. "laptop", "running shoes", "insulated flask",
  "brand": brand name in lower case or null,
  "specs": {"ram_gb": number|null, "storage_gb": number|null, "screen_inches": number|null,
            "battery_mah": number|null, "camera_mp": number|null, "refresh_hz": number|null,
            "power_watts": number|null, "capacity_litres": number|null, "weight_kg": number|null,
            "ac_tons": number|null},
  "features": list of short must-have words found or clearly implied, e.g. ["5g"], ["i5"], ["gaming"], ["waterproof"],
  "colour": colour word or null,
  "audience": one of "men", "women", "boys", "girls", "kids", "unisex" or null,
  "min_price": number in rupees or null,
  "max_price": number in rupees or null,
  "search_query": the best short Google Shopping query (2-8 words) for what they want, without the price
}

Rules:
- 1 TB = 1024 GB. "50k" = 50000, "1.5 lakh" = 150000. "around X" means min 0.8X and max 1.2X.
- Only fill a spec when the customer states it or clearly implies a number. Never invent numbers.
- "good for gaming" -> features ["gaming"]; "long battery" -> features ["long battery"]; do not turn these into numbers.
- Describe what they want to buy, not what they will do with it: "something to keep tea hot" -> product "insulated flask".
- Keep the brand exactly as the customer wrote it, in lower case.
- Requests may be in Hindi (Devanagari), Hinglish ("8gb ram wala laptop 50k ke andar") or English. Always answer in English: "ke andar"/"se kam"/"tak" means max_price, "se upar"/"se zyada" means min_price, "ladkon ke liye" means audience "boys", "mummy ke liye" means "women"."""


# Wishes that are really specs ("ssd", "8gb ram") are dropped.
SPEC_WORDS = re.compile(r"\d|\b(ssd|hdd|ram|rom|storage|memory|gb|tb|mah|mp|inch(es)?|hz|watts?)\b")

_cache = OrderedDict()
_cache_lock = threading.Lock()


def llm_available():
    return bool(os.getenv("GROQ_API_KEY"))


def looks_like_sentence(query):
    """True for requests worth sending to the model, not plain keywords."""
    # Hindi in Devanagari (or any non-Latin script) always needs the model.
    if re.search(r"[^\x00-\x7f₹–—’“”]", query or ""):
        return True
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    if len(words) >= 6:
        return True
    return len(words) >= 3 and any(word in FILLER_WORDS for word in words)


# Reused connections skip a TLS handshake on every model call.
_session = reliable_session()


def chat_json(messages, max_tokens=600, timeout=TIMEOUT_SECONDS, temperature=0, models=None):
    """
    Send a chat to the first available Groq model (of models, default
    GROQ_MODELS) and return its JSON reply as a dict. Raises on any failure.
    """
    for model in models or GROQ_MODELS:
        if model in _retired_models:
            continue
        body = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # a reasoning model; keep it quick
        response = _session.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            json=body,
            timeout=timeout,
        )
        if response.status_code == 404:
            print(f"Groq model {model} is not available; trying the next one.")
            _retired_models.add(model)
            continue
        response.raise_for_status()
        break
    else:
        raise RuntimeError("no Groq model is available")
    content = response.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("model did not return an object")
    return data


def ask_model(query):
    """The model's reading of a request, as a dict. Raises on any failure."""
    return chat_json([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ])


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _text(value, limit=60):
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value[:limit] or None


def from_model(query, data, rules):
    """
    Combine the model's reading with the rule-based one. Numbers written in
    the request (read by rules) win; the model fills product, brand and
    anything only implied.
    """
    parsed = ParsedQuery(raw=rules.raw)
    parsed.product = _text(data.get("product")) or rules.product
    parsed.brand = rules.brand or _text(data.get("brand"), 30)
    parsed.brand_named = rules.brand_named or bool(parsed.brand)

    specs = {spec.kind: spec for spec in rules.specs}
    for field, kind in SPEC_FIELDS.items():
        value = _number((data.get("specs") or {}).get(field))
        if value and kind not in specs:
            label, spec_query = SPEC_FORMAT[kind]
            specs[kind] = Spec(kind, value, label(value), spec_query(value))
    parsed.specs = list(specs.values())

    # Features written in the request (i5, 5g) must match; the model's
    # other must-haves ("gaming", "waterproof") guide the search only.
    parsed.features = list(rules.features)
    for feature in data.get("features") or []:
        feature = _text(feature, 25)
        known = {f.replace(" ", "") for f in parsed.features + parsed.wishes}
        if (
            feature
            and feature.replace(" ", "") not in known
            and feature not in (parsed.product or "")
            and not SPEC_WORDS.search(feature)  # specs are read by the rules
        ):
            parsed.wishes.append(feature)
    parsed.wishes = parsed.wishes[:3]

    colour = _text(data.get("colour"), 20)
    parsed.colour = rules.colour or (colour if colour in COLOURS else None)
    audience = _text(data.get("audience"), 10)
    parsed.audience = rules.audience or AUDIENCE.get(audience or "")

    parsed.min_price = rules.min_price if rules.min_price is not None else _number(data.get("min_price"))
    parsed.max_price = rules.max_price if rules.max_price is not None else _number(data.get("max_price"))
    if parsed.min_price and parsed.max_price and parsed.min_price > parsed.max_price:
        parsed.min_price, parsed.max_price = parsed.max_price, parsed.min_price

    # With specs written as numbers, a query built from them ("hp laptop 8GB
    # RAM 500GB") finds more listings that state them than the model's
    # wording does; the model's query helps with everything else.
    parsed.model_query = None if rules.specs else _text(data.get("search_query"), 80)
    parsed.read_by_model = True
    return parsed


def understand_query(query):
    """
    Read a request: with the model for sentences when Groq is set up, else
    (or on any failure) with the rule-based reader.
    """
    rules = parse_query(query)
    if not llm_available() or not looks_like_sentence(query):
        return rules

    key = " ".join((query or "").lower().split())
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    try:
        parsed = from_model(query, ask_model(query), rules)
    except Exception as exc:
        print(f"Query model failed, using rules: {type(exc).__name__}: {exc}")
        return rules

    with _cache_lock:
        _cache[key] = parsed
        while len(_cache) > CACHE_ENTRIES:
            _cache.popitem(last=False)
    return parsed
