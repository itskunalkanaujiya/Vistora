"""
Ask my family: a board of 2-4 products that anyone with the link can vote on.

Stored in the shared cache (Upstash) for BOARD_DAYS, so the link works from any
phone. A board holds only what the card shows (name, price, store, photo and
link); votes are one per voter, and a voter can change their mind.
"""

import re
import secrets
from urllib.parse import urlparse

import shared_cache

BOARD_DAYS = 14
MIN_ITEMS = 2
MAX_ITEMS = 4
VOTER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
BOARD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,16}$")


class BoardError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _link(value):
    """An http(s) link, or None."""
    text = str(value or "")
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme in {"http", "https"} and parsed.hostname and len(text) <= 2000:
        return text
    return None


def clean_items(raw_items):
    items = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"), 140)
        if not name:
            continue
        price = raw.get("price")
        is_number = isinstance(price, (int, float)) and not isinstance(price, bool)
        items.append({
            "name": name,
            "price": float(price) if is_number and price >= 0 else None,
            "store": _text(raw.get("store"), 60),
            "image_url": _link(raw.get("image_url")),
            "url": _link(raw.get("url")),
        })
    if not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        raise BoardError(f"Pick between {MIN_ITEMS} and {MAX_ITEMS} products to ask about.")
    return items


def _key(board_id, part=""):
    return f"board:{board_id}{':' + part if part else ''}"


def create_board(title, raw_items):
    """Store a new board and return its id."""
    if not shared_cache.enabled():
        raise BoardError("Sharing isn't set up on this server yet.", 503)

    items = clean_items(raw_items)
    board_id = secrets.token_urlsafe(6)
    board = {"title": _text(title, 80) or "Which one should I buy?", "items": items}
    if not shared_cache.put(_key(board_id), board, BOARD_DAYS * 86400, wait=True):
        raise BoardError("Couldn't save the board. Please try again.", 503)
    return board_id


def read_board(board_id):
    """The board with its vote counts and voters, or raises a 404."""
    if not BOARD_ID_PATTERN.match(board_id or ""):
        raise BoardError("This board doesn't exist or has expired.", 404)
    board = shared_cache.get(_key(board_id))
    if board is None:
        raise BoardError("This board doesn't exist or has expired.", 404)

    raw = shared_cache.command("HGETALL", shared_cache.KEY_PREFIX + _key(board_id, "votes")) or []
    votes = dict(zip(raw[0::2], raw[1::2])) if isinstance(raw, list) else {}
    counts = [0] * len(board["items"])
    for choice in votes.values():
        if str(choice).isdigit() and int(choice) < len(counts):
            counts[int(choice)] += 1
    return {**board, "votes": counts, "total_votes": sum(counts), "voters": votes}


def public_board(board, voter=None):
    """What the page needs: the board and counts, and this voter's own choice (never anyone else's)."""
    mine = board["voters"].get(voter) if voter else None
    return {
        "title": board["title"],
        "items": board["items"],
        "votes": board["votes"],
        "total_votes": board["total_votes"],
        "my_vote": int(mine) if mine is not None and str(mine).isdigit() else None,
    }


def vote(board_id, voter, option):
    """Record (or change) a voter's choice, and return the updated board."""
    if not VOTER_PATTERN.match(voter or ""):
        raise BoardError("Couldn't recognise this device. Refresh and try again.")
    board = read_board(board_id)
    if not isinstance(option, int) or isinstance(option, bool) or not 0 <= option < len(board["items"]):
        raise BoardError("Pick one of the products.")

    key = shared_cache.KEY_PREFIX + _key(board_id, "votes")
    shared_cache.command("HSET", key, voter, option)
    shared_cache.command("EXPIRE", key, BOARD_DAYS * 86400)
    return public_board(read_board(board_id), voter)
