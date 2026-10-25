"""
Offline, free: the exact ordering rules being considered for the app, tried on the
saved searches. Each rule orders the listings Vistora returned for a photo; the
same answer key judges every ordering.
"""

import json
from pathlib import Path

import analyze

ROOT = Path(__file__).resolve().parents[1]


def pool_of(run):
    final = next(e for e in run["events"] if e["type"] == "final")
    seen, pool = set(), []
    for listing in (final.get("best_matches") or []) + (final.get("cheapest_alternatives") or []):
        key = listing.get("product_url") or listing.get("name")
        if key not in seen:
            seen.add(key)
            pool.append(listing)
    return pool


def old_rule(pool):
    """What the app does today: visual similarity first, title match second."""
    return sorted(pool, key=lambda l: (l.get("visual_similarity_score") is not None,
                                       l.get("visual_similarity_score") or (l.get("text_relevance_score") or 0),
                                       l.get("text_relevance_score") or 0), reverse=True)


def title_first(digits):
    def rule(pool):
        return sorted(pool, key=lambda l: (round(l.get("text_relevance_score") or 0, digits) if digits is not None
                                           else (l.get("text_relevance_score") or 0),
                                           l.get("visual_similarity_score") or 0), reverse=True)
    return rule


def without_unbuyable(rule):
    """The same ordering, after dropping accessories and news pages (unless it is what was photographed)."""
    def wrapped(pool, query=""):
        wanted = [l for l in pool
                  if not (analyze.ARTICLE.search(analyze.norm(l.get("name"))) and l.get("price") is None)
                  and not analyze.ACCESSORY.search(analyze.norm(l.get("name")))]
        return rule(wanted or pool)
    return wrapped


def score(rule, labels, runs):
    p5, hit1, hit5, acc = [], [], [], []
    for id_, run in runs.items():
        pool = pool_of(run)
        ordered = rule(pool)
        verdicts = [analyze.judge(l.get("name"), labels[id_]) for l in ordered]
        top = verdicts[:5]
        p5.append(sum(v == "exact" for v in top) / len(top) if top else 0)
        hit1.append(int(bool(verdicts) and verdicts[0] == "exact"))
        hit5.append(int("exact" in top))
        acc.append(sum(v in ("accessory", "article") for v in top) / len(top) if top else 0)
    n = len(p5)
    return {"p@5": round(sum(p5) / n, 3), "hit@1": round(sum(hit1) / n, 3), "hit@5": round(sum(hit5) / n, 3),
            "accessory_or_article@5": round(sum(acc) / n, 3)}


def main():
    labels, runs = analyze.load()
    variants = {
        "today: visual similarity first": old_rule,
        "title match first (exact score)": title_first(None),
        "title match first (rounded to 2 decimals)": title_first(2),
        "title match first (rounded to 1 decimal)": title_first(1),
        "title first + drop accessories/news": without_unbuyable(title_first(None)),
        "title first (2 dec) + drop accessories/news": without_unbuyable(title_first(2)),
    }
    results = {name: score(rule, labels, runs) for name, rule in variants.items()}
    (ROOT / "results" / "ranking_variants.json").write_text(json.dumps(results, indent=1), encoding="utf8")
    for name, r in results.items():
        print(f"{name:46} P@5 {r['p@5']:.3f}  Hit@1 {r['hit@1']:.3f}  Hit@5 {r['hit@5']:.3f}  acc/news@5 {r['accessory_or_article@5']:.3f}")


if __name__ == "__main__":
    main()
