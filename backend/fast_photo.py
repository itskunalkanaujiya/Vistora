"""
A switch for the fast photo provider (SearchApi.io).

Its credits are limited and do not renew, so photo search keeps using the
renewing SerpApi searches unless the fast provider is switched on. It is off by
default and can be turned on for a demo, for a number of hours, after which it
goes back off by itself, so the last credits are not used up by accident.

Two ways to turn it on:
- FAST_PHOTO=on in the environment (stays on until the setting is removed), or
- the admin address (see main.py), which needs no redeploy: the setting is kept
  in the shared cache when there is one, so every server sees it, and expires.
"""

import os
import threading
import time

import shared_cache

FLAG_KEY = "settings:fast_photo"
DEFAULT_HOURS = 4
MAX_HOURS = 48
CHECK_SECONDS = 20  # how often a server re-reads the shared setting

_lock = threading.Lock()
_override = {"on": None, "until": 0.0}  # this server's copy: on/off and when it ends (time.time())
_checked_at = 0.0


def _environment_default():
    return os.getenv("FAST_PHOTO", "").strip().lower() in {"1", "true", "on", "yes"}


def _refresh():
    """Re-read the shared setting now and then, so every server follows the same switch."""
    global _checked_at
    if not shared_cache.enabled() or time.monotonic() - _checked_at < CHECK_SECONDS:
        return
    _checked_at = time.monotonic()
    value = shared_cache.get(FLAG_KEY)
    with _lock:
        if isinstance(value, dict) and "on" in value:
            _override.update(on=bool(value["on"]), until=float(value.get("until") or 0))
        else:
            # Missing (expired, removed, or the cache is unreachable): fall back to the default, which is off.
            _override.update(on=None, until=0.0)


def enabled() -> bool:
    _refresh()
    with _lock:
        if _override["on"] is not None and time.time() < _override["until"]:
            return _override["on"]
    return _environment_default()


def turn_on(hours=DEFAULT_HOURS):
    """Switch it on for some hours (1 to 48). Returns the state."""
    hours = min(MAX_HOURS, max(1.0, float(hours)))
    until = time.time() + hours * 3600
    with _lock:
        _override.update(on=True, until=until)
    if shared_cache.enabled():
        shared_cache.put(FLAG_KEY, {"on": True, "until": until}, int(hours * 3600), wait=True)
    return state()


def turn_off():
    """Switch it off now, whatever the environment default says."""
    until = time.time() + MAX_HOURS * 3600
    with _lock:
        _override.update(on=False, until=until)
    if shared_cache.enabled():
        shared_cache.put(FLAG_KEY, {"on": False, "until": until}, MAX_HOURS * 3600, wait=True)
    return state()


def state():
    with _lock:
        runtime = _override["on"] is not None and time.time() < _override["until"]
        until = _override["until"] if runtime else None
    return {
        "on": enabled(),
        "source": "admin switch" if runtime else "environment (FAST_PHOTO)",
        "until": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(until)) if until and runtime and _override["on"] else None,
        "environment_default": _environment_default(),
    }


def reset():
    """Forget the setting on this server (for tests)."""
    global _checked_at
    with _lock:
        _override.update(on=None, until=0.0)
    _checked_at = 0.0
