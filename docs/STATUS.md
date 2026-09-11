# Where the project is

Plain language. For explaining this to someone else, or to yourself in two
weeks.

---

## What this project actually does

Every hour, automatically:

1. Asks Open-Meteo what the air in Jakarta is like right now, and saves it.
2. Uses a trained model to predict the next 24 hours, and **writes those 24
   predictions down with a timestamp**.
3. Waits.

Later, when those hours actually arrive, step 1 records what really happened.
Now the prediction and the reality sit in the same database and the error is
just a join between them.

**Why that ordering matters:** the prediction is written before the answer
exists. Nobody can go back and adjust it. Most ML portfolio projects report
accuracy on a held-out test split, which is a number you can quietly tune
until it looks good. This one reports accuracy against hours that had not
happened yet when the claim was made.

Two other pieces make it MLOps rather than ML:

- **The gate.** A newly trained model is only promoted if it beats "same hour
  last week". If it loses, it is recorded as `rejected` and the old model
  keeps serving. Rejected rows are never deleted — they are the evidence that
  the gate does something.
- **The benchmark.** CAMS (Europe's operational forecast) predicts the same
  hours. If our error rises, the benchmark says whether the model decayed or
  the week was just hard.

---

## Done (Parts 1-7) — the pipeline now runs without you

| | Status |
|---|---|
| Database (Supabase, Singapore) | Running, free tier |
| 3 months of history | 2,208 hourly rows, growing hourly |
| Trained model | `v20260910-1458`, holdout MAE **22.99** vs baseline **30.55** |
| Logged forecasts | All genuinely in the future |
| API (4 endpoints) | Verified, screenshots in `docs/images/` |
| Dashboard | Runs locally |
| Repo | github.com/brio-amarta/pm25-pipeline |
| **Hourly cron** | **Green. Fires at :10 every hour on GitHub Actions** |

### First real accuracy measurement (2026-09-11)

| | MAE |
|---|---|
| Holdout, at training time | 22.99 |
| Naive baseline, at training time | 30.55 |
| **Live, on 36 scored forecasts** | **34.51** |
| **CAMS, same hours** | **28.53** |

The model scored 22.99 on a held-out split and 34.51 against reality. It is
currently losing both to CAMS and to the baseline it beat to get promoted.

That gap is the finding, not a failure. A notebook would have reported 22.99
and stopped. This committed to 36 predictions before the answers existed and
got graded by time. Note it, do not tune on it — 36 predictions over one day
is one weather pattern, not evidence. Revisit after a week of cron data, then
break MAE down per horizon before touching any features.

### Three bugs found along the way

All three passed their checkpoints. The pipeline ran, the gate promoted, the
endpoints returned 200 — and it was still wrong. Full write-ups in
`DECISIONS.md`:

1. **Actuals were 16 hours stale**, so 16 of every 24 "predictions" were
   about hours that had already happened.
2. **The benchmark was scoring itself** — CAMS error came out as exactly
   0.0, because for past hours the forecast API returns the same numbers the
   actuals API does.
3. **Duplicate rows** — `run_at` was in the primary key, so the
   de-duplication clause never fired and every run doubled the table.

Plus two caught before they fired: `models/active.pkl` is gitignored and had
to be force-added or the cron would have had no model, and `retrain.yml`
needed `permissions: contents: write` to push a promoted model back.

This is the most interesting part of the project to talk about. Not that the
pipeline works, but that a broken one looks identical from the outside.

---

## Left to do

| Part | What | Time | Can you skip it? |
|---|---|---|---|
| 8 | Docker | 45 min | No — fast, and catches problems cheaply |
| 9 | Public URL (Cloud Run *or* Render) | 15 min – 2 hrs | No — the URL is the deliverable |
| 10 | Auto-deploy on push | 45 min | Yes, easiest cut. Free on Render |
| 11 | Public dashboard (Streamlit Cloud) | 30 min | Almost no |
| 12 | README | 45 min | **No.** Highest value per hour in the project |

### Part 7 is done. The clock is running.

The hourly job is live, so scored forecasts now accumulate whether or not
anyone is at the laptop. Nothing below is urgent; all of it is deployment and
it keeps.

One thing that does not keep: GitHub disables scheduled workflows on repos
with no activity for about 60 days. Any commit resets that clock.

### The one real decision: Cloud Run or Render (Part 9)

|  | Cloud Run | Render |
|---|---|---|
| Card required | Yes, even for free tier | No |
| Cost here | $0 | $0 |
| Setup | ~2 hrs, IAM is the pain | ~15 min |
| Cold start | 1-2 sec | ~1 min after 15 min idle |
| Auto-deploy | Part 10 | Built in |

Either is defensible. If you go Cloud Run, cap IAM at 90 minutes and bail to
Render if it beats you. If you go Render, put one line in the README about
cold starts — a named tradeoff reads as a decision, an unnamed one reads as
an oversight.

---

## Known limitation, stated on purpose

"What really happened" here is CAMS model reanalysis, not a physical sensor.
So the honest phrasing of every error number is *forecast skill measured
against CAMS's own later analysis*. Switching to real station data (OpenAQ)
would be more truthful and would also mean a new dependency, station gaps,
and retraining from scratch — while changing nothing about the mechanics this
project is demonstrating. Reasoning in `DECISIONS.md`.
