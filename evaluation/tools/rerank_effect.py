"""
Does Vistora's own re-ranking (CLIP visual similarity, then price and stock
checks) improve on the order Google Lens returned? Each saved run keeps three
lists: the Lens order (first "preview"), the visually re-ranked one (second
"preview") and the final one. This compares them with the same answer key. No
search provider is called, so it costs nothing.
"""

import json
from pathlib import Path

import analyze

ROOT = Path(__file__).resolve().parents[1]


def lists(run):
    previews = [e for e in run["events"] if e["type"] == "preview"]
    lens = next((e for e in previews if e.get("ranked") is False), None)
    ranked = next((e for e in previews if e.get("ranked") is True), None)
    final = next((e for e in run["events"] if e["type"] == "final"), None)
    return lens, ranked, final


def score(listings, label):
    verdicts = [analyze.judge(l.get("name"), label) for l in listings]
    top5 = verdicts[:5]
    return {
        "p@5": sum(v == "exact" for v in top5) / len(top5) if top5 else None,
        "hit@1": int(bool(verdicts) and verdicts[0] == "exact"),
        "hit@5": int("exact" in top5),
        "accessory@5": sum(v == "accessory" for v in top5) / len(top5) if top5 else None,
    }


def main():
    labels, runs = analyze.load()
    totals = {"Google Lens order": [], "After visual re-ranking": [], "Final (prices checked)": []}
    for id_, run in runs.items():
        lens, ranked, final = lists(run)
        if not (lens and ranked and final):
            continue
        totals["Google Lens order"].append(score(lens.get("best_matches") or [], labels[id_]))
        totals["After visual re-ranking"].append(score(ranked.get("best_matches") or [], labels[id_]))
        totals["Final (prices checked)"].append(score(final.get("best_matches") or [], labels[id_]))

    summary = {}
    for name, rows in totals.items():
        summary[name] = {
            "photos": len(rows),
            **{k: round(analyze.mean([r[k] for r in rows]), 4) for k in ("p@5", "hit@1", "hit@5", "accessory@5")},
        }
    (ROOT / "results" / "rerank_effect.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
