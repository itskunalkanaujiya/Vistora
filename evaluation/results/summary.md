# Vistora evaluation: how well photo search works

Oct 2026 · 33 real product photos · 11 products · every search run through the real pipeline

## Summary

The correct product is almost always in the top five (97% of photos), the right listings come from several Indian marketplaces, and prices match the seller's page (95% within 1% where they could be checked). The weak points are speed (median 10.6 s, slower when the fast provider fails) and putting the exact model first (61% of photos).

- **Accuracy:** Precision@5 is 61%, Precision@10 66%, Hit@1 61%, Hit@5 97% and Hit@10 100%.
- **Marketplaces:** 107 different stores returned at least one correct listing, including 7 of the 13 major Indian marketplaces tracked.
- **Prices:** 83% of correct listings show a price; of 41 prices that could be compared with the seller's page, 95% matched within 1%.
- **Speed:** first results after a median 6.6 s, finished after a median 10.6 s (95th percentile 28.6 s).
- **Weakest case:** Apple Watch (correct product in the top five for 67% of its photos).
- **A surprise:** Vistora's visual re-ranking did not improve exact-model accuracy over Google Lens's own order (see "Does the re-ranking help?"). Ordering by title match first looks much better and is the clearest next improvement.

## How it was tested

- **Photos:** 33 real photographs from Wikimedia Commons (free licences, credited in `photo_credits.csv`): 11 products, 3 different photos of each, chosen so angle, lighting and background differ. 12 have a clean backdrop, 18 are real-world scenes (desk, floor, outdoors, in a hand) and 3 are close-ups.
- **Searches:** each photo was searched once through the same code the web app uses: Google Lens through SearchApi.io (SerpApi as the backup), CLIP re-ranking, seller-page price reading and Serper price look-up. The shared cache was switched off so every search was a real one.
- **Answer key:** a listing counts as correct only if its title names the model (and the brand where the model name alone is not distinctive) and is not an accessory (screen protector, cover, skin, strap) or an article (news, review). Titles with the brand missing or misspelled therefore count as wrong, which keeps the numbers cautious.
- **Checking the key:** I read 55 judged listings by hand: 50 agreed with a person's judgement, 2 news pages that counted as products were fixed with the article rule, and 3 were cautious misses (brand-less or misspelled seller titles). Every judged listing is in `judged_top5.csv` for a supervisor to check.
- **Cost:** 33 photo searches (30 fast, 3 on the backup provider) and 33 price look-ups; everything else was calculated from the saved answers at no cost.

## Results against the research gaps

| Research problem | Metric | Result |
| --- | --- | --- |
| Visually similar products may not be exact matches | Precision@5 / @10 | 61% / 66% |
| | Exact product ranked first (Hit@1) | 61% |
| | Exact product in the top 5 / top 10 (Hit@5 / Hit@10) | 97% / 100% |
| User photos differ from catalogue images | Recall@5 / @10 (of the correct listings returned) | 30% / 60% |
| | Hit@5 on real-world photos vs clean backdrops | 94% vs 100% |
| Results limited to one marketplace | Stores with a correct listing | 107 stores; 2.8 major marketplaces per photo on average |
| Prices missing or inaccurate | Price availability on correct listings | 83% |
| | Price accuracy vs the seller page | 95% within 1%, 98% within 15% (n = 41) |
| Search can take too long | Median / 95th percentile time to finish | 10.6 s / 28.6 s |
| Similar products differ in attributes | Right brand ranked first / exact model ranked first | 88% / 61% |
| | Accessories in the top 10 | 5.5% |

Recall here means the share of the correct listings Vistora returned that appear in the top 5 or 10. Because about 12 correct listings come back per photo, Recall@5 cannot exceed about 41%, so Precision and Hit are the better measures.

## Speed

| Stage | Median | 95th percentile | Fastest | Slowest |
| --- | --- | --- | --- | --- |
| First results (Google Lens matches) | 6.6 s | 24.6 s | 4.6 s | 25.7 s |
| Ranked by visual similarity | 8.7 s | 26.4 s | 6.2 s | 26.6 s |
| Finished (seller-page prices checked) | 10.6 s | 28.6 s | 7.6 s | 29.6 s |

3 of 32 searches (9%) took about 28 s because the fast provider's connection was reset and the app fell back to the slower one. Without those, the median is 10.6 s and the 95th percentile 13.6 s. The first search of the run is left out, because it ran while the image model was still loading.

## Results by product

| Product | Precision@5 | Hit@1 | Hit@5 | Stores per photo | Price shown |
| --- | --- | --- | --- | --- | --- |
| Casio F-91W watch | 53% | 67% | 100% | 3.3 | 92% |
| Converse Chuck Taylor | 53% | 67% | 100% | 3.0 | 92% |
| Apple AirPods Max | 47% | 33% | 100% | 4.0 | 88% |
| Ray-Ban Wayfarer | 60% | 67% | 100% | 2.7 | 88% |
| Nike Air Force 1 | 80% | 100% | 100% | 1.3 | 85% |
| Apple Watch | 27% | 0% | 67% | 1.0 | 54% |
| Kindle Paperwhite | 53% | 33% | 100% | 2.7 | 79% |
| JBL Flip speaker | 80% | 67% | 100% | 4.0 | 93% |
| Logitech MX Master mouse | 87% | 67% | 100% | 4.0 | 82% |
| Adidas Stan Smith | 80% | 67% | 100% | 3.3 | 96% |
| Samsung Galaxy Buds | 49% | 100% | 100% | 2.0 | 60% |

## Results by how the photo was taken

| Photo type | Photos | Precision@5 | Hit@1 | Hit@5 |
| --- | --- | --- | --- | --- |
| Clean backdrop | 12 | 67% | 42% | 100% |
| Close-up | 3 | 49% | 100% | 100% |
| Real-world | 18 | 59% | 67% | 94% |

Photos with a clean backdrop did not do better than real-world photos at putting the exact model first, so the weakness is in telling similar models apart, not in coping with messy photos.

## Does the re-ranking help?

Each search keeps the order Google Lens returned and the order after Vistora's visual re-ranking, so the two can be compared on the same photos.

| Order | Precision@5 | Hit@1 | Hit@5 | Accessories in top 5 |
| --- | --- | --- | --- | --- |
| Google Lens order | 68% | 70% | 97% | 6% |
| After visual re-ranking | 60% | 61% | 97% | 8% |
| Final (prices checked) | 61% | 61% | 97% | 8% |

Visual re-ranking lowered exact-model accuracy. Visual similarity rewards look-alikes (a JBL Flip 3 looks like a Flip 4, a case looks like the thing it covers), which a model-name check does not reward. It may still help shoppers who want something that looks the same, so the claim to make is "surfaces the closest-looking items", not "improves exact matches".

An offline test with the saved data tried other orderings:

| Ordering | Precision@5 | Hit@1 | Hit@5 |
| --- | --- | --- | --- |
| Google Lens order alone | 68% | 70% | 97% |
| Vistora visual order alone | 61% | 61% | 97% |
| Title match first, then Lens order | 87% | 88% | 100% |
| Title match first, then visual order | 88% | 94% | 100% |
| Blend (k=10, visual weight 0.5) | 67% | 58% | 100% |

Putting listings whose titles best match the identified product first gave the biggest gain. Treat it as a direction, not a result: the ranking and the answer key both read titles, so part of the gain is expected, and it was tried on the same 33 photos. It needs checking on new photos judged by people.

## After the changes: checked on 15 fresh photos

Three changes followed from this evaluation: results are ordered by how well the title matches the identified product (visual similarity only breaks ties), accessories and news pages are dropped from the results, and a connection reset is retried once. The fast provider was also switched off by default to keep its limited credits. They were checked on 15 new photos of 5 products that were not in the first set (Nintendo Switch, GoPro, Sony DualSense, Bose QuietComfort, Fitbit Charge), searched once each with the new code.

| Order | Precision@5 | Hit@1 | Hit@5 | Accessories or news in top 5 |
| --- | --- | --- | --- | --- |
| Google Lens order | 78% | 67% | 93% | 1% |
| Old rule (visual similarity first), same listings | 75% | 67% | 93% | 5% |
| New code (title match first, accessories dropped) | 82% | 87% | 87% | 8% |

- **Better first result:** the exact product is ranked first for 87% of the fresh photos, up from 67%, and Precision@5 rose from 75% to 82%.
- **Smaller than the first estimate:** the first set suggested 94% for Hit@1. That figure was measured on the same photos used to choose the rule, so the fresh-photo figure is the one to quote.
- **One photo got worse:** Hit@5 fell from 93% to 87% (one photo of 15). A grey Switch Lite was identified by Google Lens as a "Nintendo Switch dock", so ordering by title put five docks first. Ordering by title trusts the identification: when it is wrong, the results follow it. Keeping the visually closest listings in the top five was tried and did not help, so it was not added. The "Not quite? Refine" button lets a shopper correct a wrong identification.
- **Accessories:** apart from that photo, accessories and news pages in the top five were about 1% of listings.
- **Speed with the fast provider off:** these searches used only the backup provider and finished in a median 8.6 s (first results 3.8 s, 95th percentile 13.6 s), with no connection failures. That is no slower than the fast-provider run above (10.6 s), but the photos and the time of day differed, so it is a hint, not a comparison.
- **Credits used for this check:** 14 backup photo searches and 15 price look-ups; the fast provider's remaining credits were not touched.

## What this means for the project

1. **Strengths to claim:** the correct product is nearly always in the top five; results come from many Indian stores; prices are present for most listings and agree with the seller's page.
2. **Weaknesses to state honestly:** the exact model is first for about six photos in ten; searches take about 10 s and sometimes 28 s; a worn Apple Watch returned only other brands' smartwatches.
3. **Improvements made after this evaluation:** order by title match before visual similarity; retry when the fast provider's connection resets (it cost 17 s on 3 of 33 searches); drop accessories and news pages from the first results. See "After the changes" above for how they did on fresh photos.

## Limits of this evaluation

- **Small samples:** 33 photos of 11 products, then 15 photos of 5 more, each searched once. A 95th percentile from 32 timings is rough.
- **Photo source:** Wikimedia Commons photographs are mostly clear, well-lit shots, so real phone photos may do worse.
- **Judging:** the answer key is a title rule, checked by hand on 55 listings by the author. A supervisor should check `judged_top5.csv`.
- **Price check:** many prices are read from the same seller pages, so agreement is partly expected. It shows prices are consistent and in rupees, not that they are right for every store.
- **Moving target:** search results and prices change daily, so a re-run will give slightly different numbers.

## Files

`evaluation/` holds the photos, `labels.json` (answer key), `runs/` (raw saved answers), `results/` (all tables) and `tools/` (the scripts). `python tools/run_searches.py` repeats the searches and `python tools/analyze.py` recalculates every number without spending credits.
