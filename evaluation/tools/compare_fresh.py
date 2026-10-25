"""
Before/after on photos the change was not tuned against (EVAL_SET=fresh).

For each fresh photo the saved search holds: Google Lens's own order (first preview),
the order the new code returned, and the listings it returned. The old rule (visual
similarity first) is applied to those same listings, so the three orderings are
judged by the same answer key. Costs no credits.
"""

import json
import os

os.environ.setdefault("EVAL_SET", "fresh")

import analyze  # noqa: E402
from ranking_variants import old_rule, pool_of  # noqa: E402
from rerank_effect import lists  # noqa: E402


def metrics(listings_by_photo, labels):
    p5, hit1, hit5, unbuyable = [], [], [], []
    for id_, listings in listings_by_photo.items():
        verdicts = [analyze.judge(l.get("name"), labels[id_]) for l in listings]
        top = verdicts[:5]
        p5.append(sum(v == "exact" for v in top) / len(top) if top else 0)
        hit1.append(int(bool(verdicts) and verdicts[0] == "exact"))
        hit5.append(int("exact" in top))
        unbuyable.append(sum(v in ("accessory", "article") for v in top) / len(top) if top else 0)
    n = len(p5)
    return {"photos": n, "p@5": round(sum(p5) / n, 3), "hit@1": round(sum(hit1) / n, 3),
            "hit@5": round(sum(hit5) / n, 3), "accessory_or_article@5": round(sum(unbuyable) / n, 3)}


def main():
    labels, runs = analyze.load()
    lens, old, new = {}, {}, {}
    for id_, run in runs.items():
        lens_preview, _, final = lists(run)
        if not (lens_preview and final):
            continue
        lens[id_] = lens_preview.get("best_matches") or []
        new[id_] = final.get("best_matches") or []
        old[id_] = old_rule(pool_of(run))
    results = {
        "Google Lens order": metrics(lens, labels),
        "Old rule (visual similarity first), same listings": metrics(old, labels),
        "New code (title match first, accessories dropped)": metrics(new, labels),
    }
    per_product = {}
    for id_ in new:
        product = labels[id_]["product"]
        per_product.setdefault(product, {"old": {}, "new": {}})
        per_product[product]["old"][id_] = old[id_]
        per_product[product]["new"][id_] = new[id_]
    results["by product"] = {
        product: {"old": metrics(v["old"], labels), "new": metrics(v["new"], labels)} for product, v in per_product.items()
    }
    out = analyze.RESULTS
    out.mkdir(exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(results, indent=1), encoding="utf8")
    for name, r in results.items():
        if name == "by product":
            continue
        print(f"{name:52} P@5 {r['p@5']:.3f}  Hit@1 {r['hit@1']:.3f}  Hit@5 {r['hit@5']:.3f}  acc/news@5 {r['accessory_or_article@5']:.3f}")
    print("--- by product (old -> new)")
    for product, v in results["by product"].items():
        print(f"{product:20} P@5 {v['old']['p@5']:.2f} -> {v['new']['p@5']:.2f}   Hit@1 {v['old']['hit@1']:.2f} -> {v['new']['hit@1']:.2f}   Hit@5 {v['old']['hit@5']:.2f} -> {v['new']['hit@5']:.2f}")


if __name__ == "__main__":
    main()
