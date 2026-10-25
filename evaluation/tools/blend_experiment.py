"""
Offline experiment (no search credits): would blending Google Lens's order with
Vistora's visual order beat either alone? Uses reciprocal rank fusion over the
listings in the two saved lists. This is tried on the same 33 photos it is
measured on, so it only suggests a direction: it has to be confirmed on new photos.
"""

import json
from pathlib import Path

import analyze
from rerank_effect import lists

ROOT = Path(__file__).resolve().parents[1]
MISSING = 12  # rank given to a listing absent from one list


def key(listing):
    return listing.get("product_url") or listing.get("name")


def fused(lens_list, clip_list, k, clip_weight):
    ranks_lens = {key(l): i for i, l in enumerate(lens_list)}
    ranks_clip = {key(l): i for i, l in enumerate(clip_list)}
    items = {key(l): l for l in lens_list + clip_list}
    scored = []
    for name, listing in items.items():
        score = 1 / (k + ranks_lens.get(name, MISSING)) + clip_weight / (k + ranks_clip.get(name, MISSING))
        scored.append((score, listing))
    return [l for _, l in sorted(scored, key=lambda pair: -pair[0])]


def evaluate(order_fn, labels, runs):
    p5, hit1, hit5 = [], [], []
    for id_, run in runs.items():
        lens, ranked, final = lists(run)
        if not (lens and final):
            continue
        listings = order_fn(lens.get("best_matches") or [], final.get("best_matches") or [])
        verdicts = [analyze.judge(l.get("name"), labels[id_]) for l in listings]
        top = verdicts[:5]
        p5.append(sum(v == "exact" for v in top) / len(top) if top else 0)
        hit1.append(int(bool(verdicts) and verdicts[0] == "exact"))
        hit5.append(int("exact" in top))
    return {"photos": len(p5), "p@5": round(sum(p5) / len(p5), 4), "hit@1": round(sum(hit1) / len(hit1), 4),
            "hit@5": round(sum(hit5) / len(hit5), 4)}


def main():
    labels, runs = analyze.load()
    results = {
        "Google Lens order alone": evaluate(lambda lens, clip: lens, labels, runs),
        "Vistora visual order alone": evaluate(lambda lens, clip: clip, labels, runs),
    }
    def by_title(lens, clip, tie_to_lens=True):
        """Listings whose title matches the identified product best come first."""
        ranks_lens = {key(l): i for i, l in enumerate(lens)}
        items = {key(l): l for l in lens + clip}
        order = sorted(items.values(), key=lambda l: (-(l.get("text_relevance_score") or 0), ranks_lens.get(key(l), MISSING)))
        return order

    results["Title match first, then Lens order"] = evaluate(by_title, labels, runs)

    def by_title_and_visual(lens, clip):
        ranks_clip = {key(l): i for i, l in enumerate(clip)}
        items = {key(l): l for l in lens + clip}
        return sorted(items.values(), key=lambda l: (-(l.get("text_relevance_score") or 0), ranks_clip.get(key(l), MISSING)))

    results["Title match first, then visual order"] = evaluate(by_title_and_visual, labels, runs)

    for k in (3, 10, 30):
        for weight in (0.5, 1.0):
            results[f"Blend (k={k}, visual weight {weight})"] = evaluate(
                lambda lens, clip, k=k, w=weight: fused(lens, clip, k, w), labels, runs
            )
    (ROOT / "results" / "blend_experiment.json").write_text(json.dumps(results, indent=1), encoding="utf8")
    for name, r in results.items():
        print(f"{name:38} P@5 {r['p@5']:.3f}  Hit@1 {r['hit@1']:.3f}  Hit@5 {r['hit@5']:.3f}")


if __name__ == "__main__":
    main()
