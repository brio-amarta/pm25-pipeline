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

## Done (Parts 1-6) — everything on the laptop

| | Status |
|---|---|
| Database (Supabase, Singapore) | Running, free tier |
| 3 months of history | 2,208 hourly rows |
| Trained model | `v20260910-1458`, MAE **22.99** vs baseline **30.55** |
| 24 logged forecasts | All genuinely in the future |
| API (4 endpoints) | Verified, screenshots in `docs/images/` |
| Dashboard | Runs locally |

**The pipeline works end to end.** Everything below is about putting it
somewhere other people can reach.

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

This is the most interesting part of the project to talk about. Not that the
pipeline works, but that a broken one looks identical from the outside.

---

## Left to do

| Part | What | Time | Can you skip it? |
|---|---|---|---|
| **7** | GitHub + hourly cron | 30 min | **No.** This is what makes it run without you |
| 8 | Docker | 45 min | No — fast, and catches problems cheaply |
| 9 | Public URL (Cloud Run *or* Render) | 15 min – 2 hrs | No — the URL is the deliverable |
| 10 | Auto-deploy on push | 45 min | Yes, easiest cut. Free on Render |
| 11 | Public dashboard (Streamlit Cloud) | 30 min | Almost no |
| 12 | README | 45 min | **No.** Highest value per hour in the project |

### Do Part 7 first, today

Nothing else is urgent, but this is. The moment the hourly job is live, the
pipeline starts collecting real scored forecasts on its own. The dashboard's
error charts need roughly 48 hours of elapsed time before they show anything
— and that is the one thing you cannot speed up later by working harder.

Start the clock, then go build the Swift app. Come back to Parts 8-12 when
the data has accumulated.

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
