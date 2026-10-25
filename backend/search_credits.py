"""
What each search provider has left, as last read from its account.

The usage endpoint reads the accounts (SerpApi, SearchApi.io, Serper.dev) and
records the counts here. The search code uses them to skip a provider that is
known to be out of credits, instead of spending seconds on a call that is
bound to fail, and to give a clear message when every provider is empty.

A count is only trusted for a few minutes: credits are renewed or topped up
outside this app, and an old "empty" must never block searches for long.
"""

import threading
import time

TRUST_SECONDS = 10 * 60

# provider -> (searches left, when it was read)
_left = {}
_lock = threading.Lock()

LIMIT_MESSAGE = (
    "Search is at its limit for now. The monthly search credits are used up, so "
    "new searches are paused. Searches you've already run still load instantly. "
    "Please try again later."
)


class SearchLimitError(RuntimeError):
    """Every provider that could answer is out of credits; safe to show users."""

    user_facing = True
    status_code = 503

    def __init__(self, message=LIMIT_MESSAGE):
        super().__init__(message)


def record(provider, left):
    """Remember how many searches a provider has left (None = unknown)."""
    with _lock:
        if left is None:
            _left.pop(provider, None)
        else:
            _left[provider] = (int(left), time.monotonic())


def known_empty(provider):
    """True when the provider was recently read as having no searches left."""
    with _lock:
        entry = _left.get(provider)
    return bool(entry) and entry[0] <= 0 and time.monotonic() - entry[1] < TRUST_SECONDS


def left(provider):
    """How many searches a provider was recently read as having left, or None."""
    with _lock:
        entry = _left.get(provider)
    if entry and time.monotonic() - entry[1] < TRUST_SECONDS:
        return entry[0]
    return None


def clear():
    with _lock:
        _left.clear()
