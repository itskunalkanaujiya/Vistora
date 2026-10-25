# Vistora evaluation

How well photo search works on 33 real product photos (11 products, 3 photos each).
The write-up is `results/summary.md` (also `docs/Vistora_evaluation.docx`).

- `photos/` and `labels.json`: the test photos and the answer key. Credits and licences are in `photo_credits.csv` (Wikimedia Commons).
- `runs/`: the raw saved answer of every search, with timings. Calculations read these, so they cost no search credits.
- `results/`: every table (`metrics.json`, `per_photo.csv`, `judged_top5.csv`, `price_check.csv`, `rerank_effect.json`, `blend_experiment.json`, `summary.md`).
- `tools/`: the scripts, run from this folder with the backend's Python.

```
python tools/fetch_candidates.py      # find candidate photos (free)
python tools/select_photos.py         # build the test set and answer key
python tools/run_searches.py          # SPENDS search credits: one photo search + one price look-up per photo not yet saved
python tools/analyze.py               # accuracy, marketplaces, prices, time (free)
python tools/check_prices.py          # compare shown prices with the seller pages (free)
python tools/rerank_effect.py         # Lens order vs visual re-ranking (free)
python tools/blend_experiment.py      # other orderings, offline (free)
python tools/make_report.py           # write results/summary.md (free)

# The second, fresh set (5 products, 15 photos), to check a change on photos it was not tuned against:
python tools/fetch_candidates.py --fresh && python tools/select_fresh.py
EVAL_SET=fresh python tools/run_searches.py   # SPENDS credits: set FAST_PHOTO=off to keep the fast provider's
EVAL_SET=fresh python tools/analyze.py        # limited credits; analyze, then compare with the old ordering:
EVAL_SET=fresh python tools/compare_fresh.py
```

`run_searches.py` skips photos that already have a saved answer, starts its own backend on port 8001 with the shared cache off, and stops before spending if search credits are low.
