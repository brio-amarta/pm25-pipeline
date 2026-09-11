# Which files answer which guiding question

One repo rather than one folder per question. Splitting them would break the
imports and produce three projects that each do a third of a thing. The
mapping below is how the board connects to the code.

| # | Question | Needs code? | Files |
|---|---|---|---|
| 1 | Where does this break if I walk away for a month? | Design | `sql/schema.sql`, `.github/workflows/hourly.yml`, `src/api.py` (`/health`) |
| 2 | Which parts of a production loop are essential, and which are cargo cult? | No | `docs/RESEARCH.md` (yours to write) |
| 3 | How do I tell the model got worse from the world getting harder? | **Yes** | `src/train.py`, `src/features.py`, `src/fetch.py` (CAMS benchmark) |
| 4 | What changes when the model lives on devices I don't control? | No | Decision paragraph, README next steps |
| 5 | What's the smallest version that still proves I can operate a model? | No | Scope note, README |
| 6 | What would convince a skeptic this is running and not a screenshot? | **Yes** | `dashboard/app.py`, `pending_forecasts` view in `sql/schema.sql` |

## Where each answer physically lives

**Question 1.** The failure modes are commented in the workflow files. The
`/health` endpoint returns `data_age_hours` and reports `stale` rather than
`ok` when ingestion has stopped, because a 200 with month-old data is the
exact failure this question is about.

**Question 3.** Three pieces: `naive_baseline()` in `features.py` is the
floor, `fetch_cams_forecast()` pulls a reference that lived through the same
week, and the gate block in `train.py` is where "worse" gets defined
numerically instead of by feel.

**Question 6.** The `pending_forecasts` view is the answer. It returns rows
predicting hours that have not happened yet. Block 1 of the dashboard
displays the count, because that number is impossible to produce after the
fact.
