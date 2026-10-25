"""
Run every test photo through Vistora's real photo search and save the raw
answers, with timings, to evaluation/runs/. Photos already saved are skipped,
so a re-run spends no credits.

    python run_searches.py --only casio-f91w/1   # one photo (a pilot)
    python run_searches.py                       # all photos not yet saved

It starts its own copy of the backend on port 8001: the shared Upstash cache is
switched off (so the live cache is not touched or polluted) and the per-visitor
search limit is off. It stops before spending if search credits are too low.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT.parent / "backend"
SET = ("_" + os.environ["EVAL_SET"]) if os.environ.get("EVAL_SET") else ""
RUNS = ROOT / f"runs{SET}"
LABELS = ROOT / f"labels{SET}.json"
PORT = 8001
BASE = f"http://127.0.0.1:{PORT}"

# Credits to leave untouched for real visitors.
KEEP_PHOTO_CREDITS = 25
KEEP_SERPER_SEARCHES = 150


def usage():
    return requests.get(f"{BASE}/api/v1/usage", timeout=30).json()


def photo_credits(data):
    fast = (data.get("fast_photo") or {}).get("searches_left") or 0
    return fast + (data.get("searches_left") or 0), fast


def start_backend():
    RUNS.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "UPSTASH_REDIS_REST_URL": "",
        "UPSTASH_REDIS_REST_TOKEN": "",
        "KV_REST_API_URL": "",
        "KV_REST_API_TOKEN": "",
        "SEARCH_LIMIT": "0",
        # The fast provider is off by default in the app; the evaluation measures the fast path unless told otherwise.
        "FAST_PHOTO": os.environ.get("FAST_PHOTO", "on"),
        "PYTHONIOENCODING": "utf-8",
    }
    log_path = ROOT / "runs" / "backend.log"
    offset = log_path.stat().st_size if log_path.exists() else 0
    log = open(log_path, "ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=BACKEND, env=env, stdout=log, stderr=log,
    )
    for _ in range(150):
        try:
            if requests.get(f"{BASE}/health", timeout=2).ok:
                # Wait for the image model too, so the first search is not timed while it loads.
                with open(log_path, "rb") as handle:
                    handle.seek(offset)
                    if b"CLIP model loaded" in handle.read():
                        return process
        except requests.RequestException:
            pass
        time.sleep(1)
    process.kill()
    raise SystemExit("The backend did not start.")


def search(photo_path):
    """One photo search through the streaming endpoint; every event with its time."""
    started = time.perf_counter()
    events, marks = [], {}
    with open(photo_path, "rb") as handle:
        response = requests.post(
            f"{BASE}/api/v1/products/search-by-image/stream",
            files={"file": ("photo.jpg", handle, "image/jpeg")},
            stream=True, timeout=240,
        )
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            at = round(time.perf_counter() - started, 3)
            kind = event["type"]
            if kind == "preview":
                kind = "preview_ranked" if event.get("ranked") else "preview_lens"
            marks.setdefault(kind, at)
            events.append({"at": at, **event})
    return {"timings": marks, "events": events}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="a photo id such as casio-f91w/1")
    arguments = parser.parse_args()

    labels = json.loads(LABELS.read_text(encoding="utf8"))
    todo = []
    for label in labels:
        if arguments.only and label["id"] != arguments.only:
            continue
        target = RUNS / (label["id"].replace("/", "_") + ".json")
        if not target.exists():
            todo.append((label, target))
    print(f"{len(todo)} photo(s) to search")
    if not todo:
        return

    backend = start_backend()
    try:
        before = usage()
        total_before, fast_before = photo_credits(before)
        serper_before = (before.get("text") or {}).get("searches_left") or 0
        print(f"credits before: photo {total_before} (fast {fast_before}), Serper {serper_before}")
        if total_before - len(todo) < KEEP_PHOTO_CREDITS or serper_before - len(todo) < KEEP_SERPER_SEARCHES:
            raise SystemExit(f"Not enough credits to run {len(todo)} searches and keep a reserve. Stopping.")

        for number, (label, target) in enumerate(todo, 1):
            result = search(ROOT / label["file"])
            result["id"] = label["id"]
            result["ran_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            target.write_text(json.dumps(result, indent=1), encoding="utf8")
            timings = result.get("timings", {})
            print(f"[{number}/{len(todo)}] {label['id']:32} final {timings.get('final')}s  "
                  f"{'ERROR ' + result['error'] if 'error' in result else ''}", flush=True)
            if "error" in result:
                print("stopping after an error, so no credits are wasted")
                break

        after = usage()
        total_after, fast_after = photo_credits(after)
        serper_after = (after.get("text") or {}).get("searches_left") or 0
        print(f"credits used: photo {total_before - total_after} (fast {fast_before - fast_after}), "
              f"Serper {serper_before - serper_after}")
        print(f"credits left: photo {total_after} (fast {fast_after}), Serper {serper_after}")
    finally:
        backend.terminate()


if __name__ == "__main__":
    main()
