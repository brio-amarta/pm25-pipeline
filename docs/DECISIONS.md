# Decisions and known limitations

Three bugs found while working through the runbook on 2026-09-10, what each
one was, and why the fix is what it is. Plus one limitation that is not a bug
and is not going to be fixed.

Every one of these was invisible in the checkpoints. The pipeline ran, the
gate passed, the endpoints returned 200. That is the point: nothing about a
broken forecasting pipeline necessarily looks broken.

---

## 1 · Actuals were up to a day stale, so most of the horizon was retroactive

**Symptom.** `python -m src.predict` reported `wrote 24 forecasts through
2026-09-10 23:00`, only eight hours ahead of the clock. The freshest row in
`actuals` was `2026-09-09 23:00Z` — 16 hours behind.

**Cause.** `fetch_recent_actuals` called Open-Meteo with `past_days=2,
forecast_days=0`. In the air-quality API the current day sits inside the
forecast window, so `forecast_days=0` truncates at the end of *yesterday*.
The 48 rows written per run were two whole days ending at a day boundary,
never reaching the current hour. `latest_features` then builds +1h…+24h from
the last actual, so most of the horizon landed in the past.

**Why it mattered.** 16 of 24 forecast rows were claims about hours that had
already happened when they were written. The core assertion of this project —
predictions logged before the answer exists — was only true for a third of
the rows.

**Fix.** Widen the window to `forecast_days=1`, then clip to the current hour.

The clip is not optional. Past the current hour those values are CAMS model
output, and writing them into `actuals` would mean fabricating the ground
truth we score against — a worse bug than the one being fixed.

**Verified.** `hours_behind` went 16.18 → 0.25; forecasts still in the future
went 8/24 → 24/24.

---

## 2 · The benchmark was scoring itself

**Symptom.** `/metrics` returned `"benchmarks": {"cams": 0.0}` while `mae_7d`
was `null`. A CAMS mean absolute error of exactly zero would mean CAMS
forecasts Jakarta perfectly.

**Cause.** `fetch_cams_forecast` used `forecast_days=2, past_days=0`, which
includes hours already elapsed today. For those hours Open-Meteo returns its
latest analysis — the identical numbers `actuals` receives. Joining them gave
`ABS(predicted - pm25) = 0` down the whole column, confirmed by inspection:

```
target_ts                 predicted   pm25    err
2026-09-10 00:00:00+00    155.5       155.5   0
2026-09-10 01:00:00+00    104.1       104.1   0
2026-09-10 02:00:00+00     84.5        84.5   0
```

**Why it mattered.** `fetch.py` states the benchmark's purpose: *"Without it
a rise in our error is ambiguous: we cannot tell a decaying model from a
genuinely unpredictable week."* A reference identical to ground truth cannot
do that. On a dashboard it renders as **CAMS 0.0 vs our model 22.99**, which
reads as "this model is far worse than the baseline" — the opposite of what
the `models` table says.

**Fix.** Same shape as #1: keep only benchmark rows whose `target_ts` is
still in the future, so every stored row is a real forward-looking CAMS
prediction that gets scored later against a genuinely later observation.

**Consequence.** `/metrics` now reports `"benchmarks": {}` until the first
benchmark hour elapses and is ingested. Empty is correct. Zero was a lie.

---

## 3 · `ON CONFLICT DO NOTHING` was dead code

**Symptom.** Every `target_ts` in `benchmark` appeared twice after two
`predict` runs.

**Cause.** The table was keyed `PRIMARY KEY (target_ts, source, run_at)` with
`run_at DEFAULT NOW()`. Every insert therefore had a unique key, so the
`ON CONFLICT DO NOTHING` in `INSERT_BENCHMARK` had nothing to conflict on and
never fired.

**Why it mattered.** Under the hourly cron this compounds: ~48 rows written
per hour, ~1,150 per day, where ~24 distinct hours would do. Worse than the
storage, `AVG(ABS(...))` in `/metrics` silently weights whichever hours were
inserted most often, so the benchmark error would drift for no reason
connected to forecast quality.

**Fix.** `PRIMARY KEY (target_ts, source)`. One row per hour per source,
keeping CAMS's *earliest* commitment rather than its latest revision — which
matches how `forecasts` already works.

Because `init_schema` uses `CREATE TABLE IF NOT EXISTS`, editing the schema
does not alter an existing table. The table was dropped and recreated.

**Verified.** 32 rows / 32 distinct pairs, earliest target ahead of `NOW()`.
A repeat `predict` run leaves the count unchanged.

---

## Known limitation: ground truth is a model, not a measurement

`actuals` comes from Open-Meteo's air-quality API with no `domains`
parameter, which resolves to `best_match`. Outside Europe that is CAMS
global. So "what the air was really like" is CAMS reanalysis, and the
benchmark is CAMS forecast. Both legs come from the same modelling system.

The honest reading of every error number here: **forecast skill measured
against CAMS's own later analysis**, not against instruments.

**Not fixed, deliberately.** Switching `actuals` to station observations
(OpenAQ has Jakarta coverage) would be more truthful, and would also mean a
new dependency, irregular station gaps to handle, discarding the 2,208-row
history, and retraining. This project demonstrates MLOps mechanics — logging
predictions before the fact, gating promotion on a baseline, scoring by join
— and every one of those mechanisms works identically whichever series is
called ground truth. The substitution is a data-sourcing change, not an
architecture change.

Stated here rather than left for a reader to discover.

---

## Note on holdout MAE

The registry records `holdout_mae = 22.99` against a naive baseline of 30.55.
That single number averages horizons +1h through +24h together. The +1h
predictions are far better than that and the +24h ones far worse, and the
average hides both. Breaking error down per horizon is worth adding: accuracy
should decay with distance, and if it does not, something is wrong with the
features.

## Environment note

On Apple Silicon, `sklearn` emits `divide by zero` / `overflow` / `invalid
value encountered in matmul` warnings during `fit` and `predict`. These are
spurious — Apple's Accelerate BLAS leaves floating-point exception flags set
after valid work and numpy reports them. Results are correct, and the
warnings do not appear on Linux (Docker, GitHub Actions runners), which use
OpenBLAS. See numpy issue #28687.
