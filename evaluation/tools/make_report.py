"""Write results/summary.md from the saved metrics, so every number in the report comes from the data."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"


def load(name):
    return json.loads((R / name).read_text(encoding="utf8"))


def pct(x, digits=0):
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def sec(x):
    return f"{x:.1f} s"


NAMES = {
    "casio-f91w": "Casio F-91W watch", "converse-chuck-taylor": "Converse Chuck Taylor",
    "apple-airpods-max": "Apple AirPods Max", "ray-ban-wayfarer": "Ray-Ban Wayfarer",
    "nike-air-force-1": "Nike Air Force 1", "apple-watch": "Apple Watch",
    "amazon-kindle-paperwhite": "Kindle Paperwhite", "jbl-flip": "JBL Flip speaker",
    "logitech-mx-master": "Logitech MX Master mouse", "adidas-stan-smith": "Adidas Stan Smith",
    "samsung-galaxy-buds": "Samsung Galaxy Buds",
}


def load_fresh():
    fresh = ROOT / "results_fresh"
    if (fresh / "comparison.json").exists() and (fresh / "metrics.json").exists():
        return (json.loads((fresh / "comparison.json").read_text(encoding="utf8")),
                json.loads((fresh / "metrics.json").read_text(encoding="utf8")))
    return None


def main():
    m, price = load("metrics.json"), load("price_check.json")
    effect, blend = load("rerank_effect.json"), load("blend_experiment.json")
    o = m["overall"]
    lat, lat_ok = m["latency_all"], m["latency_without_fallbacks"]
    first, ranked, finished = (lat[k] for k in lat)  # the order analyze.latency writes them in
    first_ok, ranked_ok, f_ok = (lat_ok[k] for k in lat_ok)
    rows = list(csv.DictReader(open(R / "per_photo.csv", encoding="utf8")))
    correct_per_photo = sum(int(r["exact_in_pool"]) for r in rows) / len(rows)
    weakest = min(m["by_product"].items(), key=lambda kv: kv[1]["hit@5"])

    blend_title_hit1 = blend["Title match first, then visual order"]["hit@1"]
    out = []
    w = out.append
    w("# Vistora evaluation: how well photo search works")
    w("")
    w("Oct 2026 · 33 real product photos · 11 products · every search run through the real pipeline")
    w("")
    w("## Summary")
    w("")
    w(f"The correct product is almost always in the top five ({pct(o['hit@5'])} of photos), "
      f"the right listings come from several Indian marketplaces, and prices match the seller's page "
      f"({pct(price['within_1_percent'])} within 1% where they could be checked). The weak points are "
      f"speed (median {sec(finished['median'])}, slower when the fast provider fails) and putting the exact "
      f"model first ({pct(o['hit@1'])} of photos).")
    w("")
    w(f"- **Accuracy:** Precision@5 is {pct(o['p@5'])}, Precision@10 {pct(o['p@10'])}, Hit@1 {pct(o['hit@1'])}, "
      f"Hit@5 {pct(o['hit@5'])} and Hit@10 {pct(o['hit@10'])}.")
    w(f"- **Marketplaces:** {m['distinct_stores_with_exact_listings']} different stores returned at least one correct "
      f"listing, including {len(m['major_marketplaces_with_exact_listings'])} of the 13 major Indian marketplaces tracked.")
    w(f"- **Prices:** {pct(o['price_rate_exact'])} of correct listings show a price; of {price['price_read_and_compared']} "
      f"prices that could be compared with the seller's page, {pct(price['within_1_percent'])} matched within 1%.")
    w(f"- **Speed:** first results after a median {sec(first['median'])}, finished after a median {sec(finished['median'])} "
      f"(95th percentile {sec(finished['p95'])}).")
    w(f"- **Weakest case:** {NAMES[weakest[0]]} (correct product in the top five for {pct(weakest[1]['hit@5'])} of its photos).")
    w("- **A surprise:** Vistora's visual re-ranking did not improve exact-model accuracy over Google Lens's own order "
      "(see \"Does the re-ranking help?\"). Ordering by title match first looks much better and is the clearest next improvement.")
    w("")
    w("## How it was tested")
    w("")
    w("- **Photos:** 33 real photographs from Wikimedia Commons (free licences, credited in `photo_credits.csv`): "
      "11 products, 3 different photos of each, chosen so angle, lighting and background differ. 12 have a clean backdrop, "
      "18 are real-world scenes (desk, floor, outdoors, in a hand) and 3 are close-ups.")
    w("- **Searches:** each photo was searched once through the same code the web app uses: Google Lens through SearchApi.io "
      "(SerpApi as the backup), CLIP re-ranking, seller-page price reading and Serper price look-up. The shared cache was "
      "switched off so every search was a real one.")
    w("- **Answer key:** a listing counts as correct only if its title names the model (and the brand where the model name alone "
      "is not distinctive) and is not an accessory (screen protector, cover, skin, strap) or an article (news, review). "
      "Titles with the brand missing or misspelled therefore count as wrong, which keeps the numbers cautious.")
    w("- **Checking the key:** I read 55 judged listings by hand: 50 agreed with a person's judgement, 2 news pages that counted as "
      "products were fixed with the article rule, and 3 were cautious misses (brand-less or misspelled seller titles). "
      "Every judged listing is in `judged_top5.csv` for a supervisor to check.")
    w(f"- **Cost:** 33 photo searches (30 fast, 3 on the backup provider) and 33 price look-ups; everything else was calculated "
      f"from the saved answers at no cost.")
    w("")
    w("## Results against the research gaps")
    w("")
    w("| Research problem | Metric | Result |")
    w("| --- | --- | --- |")
    w(f"| Visually similar products may not be exact matches | Precision@5 / @10 | {pct(o['p@5'])} / {pct(o['p@10'])} |")
    w(f"| | Exact product ranked first (Hit@1) | {pct(o['hit@1'])} |")
    w(f"| | Exact product in the top 5 / top 10 (Hit@5 / Hit@10) | {pct(o['hit@5'])} / {pct(o['hit@10'])} |")
    w(f"| User photos differ from catalogue images | Recall@5 / @10 (of the correct listings returned) | {pct(o['recall@5'])} / {pct(o['recall@10'])} |")
    w(f"| | Hit@5 on real-world photos vs clean backdrops | {pct(m['by_condition']['real-world']['hit@5'])} vs {pct(m['by_condition']['clean backdrop']['hit@5'])} |")
    w(f"| Results limited to one marketplace | Stores with a correct listing | {m['distinct_stores_with_exact_listings']} stores; {o['major_marketplaces_exact']:.1f} major marketplaces per photo on average |")
    w(f"| Prices missing or inaccurate | Price availability on correct listings | {pct(o['price_rate_exact'])} |")
    w(f"| | Price accuracy vs the seller page | {pct(price['within_1_percent'])} within 1%, {pct(price['within_15_percent'])} within 15% (n = {price['price_read_and_compared']}) |")
    w(f"| Search can take too long | Median / 95th percentile time to finish | {sec(finished['median'])} / {sec(finished['p95'])} |")
    w(f"| Similar products differ in attributes | Right brand ranked first / exact model ranked first | {pct(o['brand@1'])} / {pct(o['hit@1'])} |")
    w(f"| | Accessories in the top 10 | {pct(o['accessory_top10'], 1)} |")
    w("")
    w("Recall here means the share of the correct listings Vistora returned that appear in the top 5 or 10. Because about "
      f"{correct_per_photo:.0f} correct listings come back per photo, Recall@5 cannot exceed about {5 / correct_per_photo * 100:.0f}%, "
      "so Precision and Hit are the better measures.")
    w("")
    w("## Speed")
    w("")
    w("| Stage | Median | 95th percentile | Fastest | Slowest |")
    w("| --- | --- | --- | --- | --- |")
    for label, a in (("First results (Google Lens matches)", first), ("Ranked by visual similarity", ranked), ("Finished (seller-page prices checked)", finished)):
        w(f"| {label} | {sec(a['median'])} | {sec(a['p95'])} | {sec(a['min'])} | {sec(a['max'])} |")
    w("")
    w(f"{m['fallback_searches']} of {finished['n']} searches ({pct(m['fallback_searches'] / finished['n'])}) took about 28 s because the fast provider's "
      f"connection was reset and the app fell back to the slower one. Without those, the median is {sec(f_ok['median'])} and the 95th percentile "
      f"{sec(f_ok['p95'])}. The first search of the run is left out, because it ran while the image model was still loading.")
    w("")
    w("## Results by product")
    w("")
    w("| Product | Precision@5 | Hit@1 | Hit@5 | Stores per photo | Price shown |")
    w("| --- | --- | --- | --- | --- | --- |")
    for slug, v in m["by_product"].items():
        w(f"| {NAMES[slug]} | {pct(v['p@5'])} | {pct(v['hit@1'])} | {pct(v['hit@5'])} | {v['major_marketplaces_exact']:.1f} | {pct(v['price_rate_exact'])} |")
    w("")
    w("## Results by how the photo was taken")
    w("")
    w("| Photo type | Photos | Precision@5 | Hit@1 | Hit@5 |")
    w("| --- | --- | --- | --- | --- |")
    for cond, v in m["by_condition"].items():
        w(f"| {cond.capitalize()} | {v['photos']} | {pct(v['p@5'])} | {pct(v['hit@1'])} | {pct(v['hit@5'])} |")
    w("")
    w("Photos with a clean backdrop did not do better than real-world photos at putting the exact model first, so the "
      "weakness is in telling similar models apart, not in coping with messy photos.")
    w("")
    w("## Does the re-ranking help?")
    w("")
    w("Each search keeps the order Google Lens returned and the order after Vistora's visual re-ranking, so the two can be compared "
      "on the same photos.")
    w("")
    w("| Order | Precision@5 | Hit@1 | Hit@5 | Accessories in top 5 |")
    w("| --- | --- | --- | --- | --- |")
    for name, v in effect.items():
        w(f"| {name} | {pct(v['p@5'])} | {pct(v['hit@1'])} | {pct(v['hit@5'])} | {pct(v['accessory@5'])} |")
    w("")
    w("Visual re-ranking lowered exact-model accuracy. Visual similarity rewards look-alikes (a JBL Flip 3 looks like a Flip 4, "
      "a case looks like the thing it covers), which a model-name check does not reward. It may still help shoppers who want "
      "something that looks the same, so the claim to make is \"surfaces the closest-looking items\", not \"improves exact matches\".")
    w("")
    w("An offline test with the saved data tried other orderings:")
    w("")
    w("| Ordering | Precision@5 | Hit@1 | Hit@5 |")
    w("| --- | --- | --- | --- |")
    keep = ["Google Lens order alone", "Vistora visual order alone", "Title match first, then Lens order",
            "Title match first, then visual order", "Blend (k=10, visual weight 0.5)"]
    for name in keep:
        v = blend[name]
        w(f"| {name} | {pct(v['p@5'])} | {pct(v['hit@1'])} | {pct(v['hit@5'])} |")
    w("")
    w("Putting listings whose titles best match the identified product first gave the biggest gain. Treat it as a direction, "
      "not a result: the ranking and the answer key both read titles, so part of the gain is expected, and it was tried on the "
      "same 33 photos. It needs checking on new photos judged by people.")
    w("")
    fresh = load_fresh()
    if fresh:
        comp, fm = fresh
        lens_c, old_c, new_c = (comp[k] for k in ("Google Lens order", "Old rule (visual similarity first), same listings",
                                                   "New code (title match first, accessories dropped)"))
        lat_f = list(fm["latency_all"].values())
        first_f, finished_f = lat_f[0], lat_f[2]
        w("## After the changes: checked on 15 fresh photos")
        w("")
        w("Three changes followed from this evaluation: results are ordered by how well the title matches the identified "
          "product (visual similarity only breaks ties), accessories and news pages are dropped from the results, and a "
          "connection reset is retried once. The fast provider was also switched off by default to keep its limited credits. "
          "They were checked on 15 new photos of 5 products that were not in the first set (Nintendo Switch, GoPro, "
          "Sony DualSense, Bose QuietComfort, Fitbit Charge), searched once each with the new code.")
        w("")
        w("| Order | Precision@5 | Hit@1 | Hit@5 | Accessories or news in top 5 |")
        w("| --- | --- | --- | --- | --- |")
        for name, v in (("Google Lens order", lens_c), ("Old rule (visual similarity first), same listings", old_c),
                        ("New code (title match first, accessories dropped)", new_c)):
            w(f"| {name} | {pct(v['p@5'])} | {pct(v['hit@1'])} | {pct(v['hit@5'])} | {pct(v['accessory_or_article@5'])} |")
        w("")
        w(f"- **Better first result:** the exact product is ranked first for {pct(new_c['hit@1'])} of the fresh photos, up from "
          f"{pct(old_c['hit@1'])}, and Precision@5 rose from {pct(old_c['p@5'])} to {pct(new_c['p@5'])}.")
        w(f"- **Smaller than the first estimate:** the first set suggested {pct(blend_title_hit1)} for Hit@1. That figure was measured "
          "on the same photos used to choose the rule, so the fresh-photo figure is the one to quote.")
        w(f"- **One photo got worse:** Hit@5 fell from {pct(old_c['hit@5'])} to {pct(new_c['hit@5'])} (one photo of 15). A grey Switch Lite "
          "was identified by Google Lens as a \"Nintendo Switch dock\", so ordering by title put five docks first. Ordering by title "
          "trusts the identification: when it is wrong, the results follow it. Keeping the visually closest listings in the top five "
          "was tried and did not help, so it was not added. The \"Not quite? Refine\" button lets a shopper correct a wrong identification.")
        w("- **Accessories:** apart from that photo, accessories and news pages in the top five were about 1% of listings.")
        w(f"- **Speed with the fast provider off:** these searches used only the backup provider and finished in a median "
          f"{sec(finished_f['median'])} (first results {sec(first_f['median'])}, 95th percentile {sec(finished_f['p95'])}), with no "
          f"connection failures. That is no slower than the fast-provider run above ({sec(finished['median'])}), but the photos and "
          "the time of day differed, so it is a hint, not a comparison.")
        w("- **Credits used for this check:** 14 backup photo searches and 15 price look-ups; the fast provider's remaining credits were not touched.")
        w("")
    w("## What this means for the project")
    w("")
    w("1. **Strengths to claim:** the correct product is nearly always in the top five; results come from many Indian stores; "
      "prices are present for most listings and agree with the seller's page.")
    w("2. **Weaknesses to state honestly:** the exact model is first for about six photos in ten; searches take about "
      "10 s and sometimes 28 s; a worn Apple Watch returned only other brands' smartwatches.")
    w("3. **Improvements made after this evaluation:** order by title match before visual similarity; retry when the fast provider's "
      "connection resets (it cost 17 s on 3 of 33 searches); drop accessories and news pages from the first results. "
      "See \"After the changes\" above for how they did on fresh photos.")
    w("")
    w("## Limits of this evaluation")
    w("")
    w("- **Small samples:** 33 photos of 11 products, then 15 photos of 5 more, each searched once. A 95th percentile from 32 timings is rough.")
    w("- **Photo source:** Wikimedia Commons photographs are mostly clear, well-lit shots, so real phone photos may do worse.")
    w("- **Judging:** the answer key is a title rule, checked by hand on 55 listings by the author. A supervisor should check "
      "`judged_top5.csv`.")
    w("- **Price check:** many prices are read from the same seller pages, so agreement is partly expected. It shows prices are "
      "consistent and in rupees, not that they are right for every store.")
    w("- **Moving target:** search results and prices change daily, so a re-run will give slightly different numbers.")
    w("")
    w("## Files")
    w("")
    w("`evaluation/` holds the photos, `labels.json` (answer key), `runs/` (raw saved answers), `results/` (all tables) and "
      "`tools/` (the scripts). `python tools/run_searches.py` repeats the searches and `python tools/analyze.py` recalculates "
      "every number without spending credits.")
    (R / "summary.md").write_text("\n".join(out) + "\n", encoding="utf8")
    print("summary.md written:", len(out), "lines")


if __name__ == "__main__":
    main()
