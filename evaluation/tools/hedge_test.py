"""Offline, free: would keeping the visually closest listings in the top five protect against a wrong identification?"""
import os, sys, json
import analyze
from ranking_variants import old_rule, pool_of


def title_first(pool):
    return sorted(pool, key=lambda l: (round(l.get("text_relevance_score") or 0, 2), l.get("visual_similarity_score") or 0), reverse=True)


def hedged(pool, keep=1, at=3):
    """Title first, but the `keep` visually closest listings are guaranteed a place in the top five (from position `at`)."""
    ordered = title_first(pool)
    by_look = sorted(pool, key=lambda l: l.get("visual_similarity_score") or 0, reverse=True)
    must = []
    for l in by_look:
        if len(must) < keep:
            must.append(l)
    top = [l for l in ordered if l not in must][:5 - len(must)]
    for offset, l in enumerate(must):
        top.insert(min(at + offset, len(top)), l)
    return top + [l for l in ordered if l not in top]


def score(rule, labels, runs):
    p5, h1, h5 = [], [], []
    for id_, run in runs.items():
        final = next((e for e in run["events"] if e["type"] == "final"), None)
        if not final:
            continue
        listings = rule(pool_of(run))
        v = [analyze.judge(l.get("name"), labels[id_]) for l in listings]
        top = v[:5]
        p5.append(sum(x == "exact" for x in top) / len(top) if top else 0)
        h1.append(int(bool(v) and v[0] == "exact"))
        h5.append(int("exact" in top))
    n = len(p5)
    return f"P@5 {sum(p5)/n:.3f}  Hit@1 {sum(h1)/n:.3f}  Hit@5 {sum(h5)/n:.3f}  (n={n})"


rules = {
    "old (visual first)": old_rule, "title first": title_first,
    "title first + 1 visual in top 5 (slot 4)": lambda p: hedged(p, 1, 3),
    "title first + 2 visual in top 5 (slots 4-5)": lambda p: hedged(p, 2, 3),
}
for setname in ("", "fresh"):
    if setname: os.environ["EVAL_SET"] = setname
    else: os.environ.pop("EVAL_SET", None)
    import importlib; importlib.reload(analyze)
    labels, runs = analyze.load()
    print("=== first set (33 photos)" if not setname else "=== fresh set (15 photos)")
    for name, rule in rules.items():
        print(f"  {name:46} {score(rule, labels, runs)}")
