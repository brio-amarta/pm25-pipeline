# Runbook

Step by step, in the order things must happen. Each step ends with a
checkpoint. Do not move on until the checkpoint passes, because every later
step assumes the earlier ones actually worked.

Rough total: 8 to 10 hours. Steps 1 to 6 run entirely on your laptop.

---

## Part 0 · Tools

### Install on your machine

| Tool | Check it's there | If missing |
|---|---|---|
| Python 3.12+ | `python3 --version` | `brew install python@3.12` |
| Git | `git --version` | `xcode-select --install` |
| Docker Desktop | `docker --version` | https://docker.com/products/docker-desktop |
| gcloud CLI | `gcloud --version` | `brew install --cask google-cloud-sdk` |

Docker and gcloud are not needed until Part 8. Do not install them today.

### Accounts to create

| Service | When | Card required |
|---|---|---|
| Supabase | **Now** (Part 2) | No |
| GitHub | Part 7 | No |
| Google Cloud | Part 9 | **Yes**, even on free tier |
| Streamlit Community Cloud | Part 11 | No |

Create only Supabase today. The other three do nothing until you have data.

### What each tool does

- **Supabase** hosts Postgres. Your four tables live here.
- **GitHub** stores the code and runs the cron and deploy jobs.
- **Cloud Run** runs the API container and gives you the public URL.
- **Streamlit Cloud** hosts the dashboard.
- **Docker** packages the API so Cloud Run can run it.
- **gcloud** is the command line tool for deploying to Cloud Run.

---

## Part 1 · Local environment  (20 min)

```bash
cd "path/to/Brio Random/pm25-pipeline"

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

**Checkpoint**

```bash
python -c "import src.config; print(src.config.settings.location_name)"
# Jakarta
```

If you get `ModuleNotFoundError: No module named 'src'`, you are in the wrong
directory. Run from the folder containing `src/`, not from inside it.

---

## Part 2 · Get the data  (45 min)

This is the first arrow on the diagram and the most important step in the
whole project. Nothing downstream works until it does.

### 2a. Create the database

1. Go to supabase.com, sign up, create a new project
2. Pick a region near you (Singapore for Jakarta)
3. Set a database password and **write it down**, it is not shown again
4. Wait about two minutes for provisioning

### 2b. Get the connection string

In your project: **Connect** (top bar) → **Connection string** → **URI**.

You will see two options. Take the **Session pooler** one, not the direct
connection. Direct connections are IPv6-only on the free tier and will fail
from most home networks and from GitHub Actions.

It looks like:

```
postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
```

### 2c. Configure

```bash
cp .env.example .env
```

Edit `.env`. Two changes to the URL you copied:

1. Replace `postgresql://` with `postgresql+psycopg://` so SQLAlchemy uses
   the right driver
2. Replace `[YOUR-PASSWORD]` with your actual password

```
DATABASE_URL=postgresql+psycopg://postgres.abcdefgh:realpassword@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
```

If your password contains `@ : / ?` or `#`, URL-encode it or change it to
something alphanumeric. This wastes more time than it should.

### 2d. Run the backfill

```bash
python -m src.backfill
```

This creates the four tables, calls Open-Meteo, and writes about three months
of hourly PM2.5.

**Checkpoint**

```
Creating schema...
Fetching history from Open-Meteo...
Wrote 2208 hourly rows, 2026-06-10 ... to 2026-09-10 ...
```

Then confirm in Supabase: **Table Editor** should show `actuals` with rows in
it, plus empty `benchmark`, `forecasts`, and `models`.

### If it breaks

| Error | Cause |
|---|---|
| `could not translate host name` | Wrong host, or you used the direct connection instead of the pooler |
| `password authentication failed` | Password wrong, or special characters not encoded |
| `No module named 'psycopg'` | `pip install -r requirements.txt` did not finish |
| `SSL connection has been closed` | Add `?sslmode=require` to the end of the URL |
| Empty response from Open-Meteo | Check your internet, then retry. The API has no key and no quota to hit. |

**You are now further than most people get.** Real data, real database, on a
schema you designed. Stop here if you are out of time today.

---

## Part 3 · Train the model  (30 min)

```bash
python -m src.train
```

**Checkpoint**

```
v20260910-1432
  holdout MAE      6.214  (504 rows)
  naive baseline   8.937
  active model     none
PROMOTED v20260910-1432 to active.
```

Three things must be true:

1. A `models/active.pkl` file now exists
2. The `models` table has one row with `status = 'active'`
3. Your MAE is **lower** than the naive baseline

### If the model loses to the baseline

You will see `REJECTED: does not beat the naive baseline.`

This is the gate working correctly, not a bug. It means the model genuinely
is not adding value on your data yet. Usually more history fixes it. Raise
`past_days` in `src/backfill.py` and re-run backfill, then train again.

Do not use `--force`. The rejected row in the `models` table is portfolio
material: it is evidence the gate does something.

---

## Part 4 · Make predictions  (20 min)

```bash
python -m src.predict
```

**Checkpoint**

```
ingest: {'actuals_written': 48, 'benchmark_written': 48}
wrote 24 forecasts through 2026-09-11 14:00:00+00:00
```

In Supabase, `forecasts` now has 24 rows, all with `target_ts` **in the
future**, and `benchmark` has CAMS values.

Those 24 rows are the entire argument of this project. They are claims about
hours that have not happened, written down and timestamped. Nothing you do
later can fabricate them.

Run `python -m src.predict` a few times over the next day. After 24 hours,
`SELECT * FROM scored_forecasts` starts returning rows and you have real
error measurements.

---

## Part 5 · Run the API locally  (20 min)

```bash
uvicorn src.api:app --reload
```

Open http://localhost:8000/docs

**Checkpoint** — all four endpoints respond:

- `/health` → `status: ok`, recent `latest_actual`
- `/forecast` → 24 points
- `/metrics` → `pending_forecasts` greater than zero
- `/models` → your one active version

Screenshot `/docs` now. It goes in the README.

---

## Part 6 · Run the dashboard locally  (30 min)

```bash
pip install -r requirements-dashboard.txt
streamlit run dashboard/app.py
```

**Checkpoint** — block 1 shows real ages ("12 min ago"), block 2 draws a
forecast curve, and block 6 lists your model.

Blocks 3, 4, and 5 will say "nothing scored yet". That is correct. They need
24 hours to pass before reality catches up. This is the project working as
designed, not a failure.

**Everything above runs on your laptop.** The full pipeline is now proven.
Everything below is putting it somewhere other people can reach.

---

## Part 7 · GitHub  (30 min)

```bash
git init
git add .
git commit -m "PM2.5 forecasting pipeline"
```

Confirm `.env` is **not** in the commit:

```bash
git status --short | grep env
# should show .env.example only, never .env
```

Create an empty repo on github.com, then:

```bash
git remote add origin https://github.com/YOURNAME/pm25-pipeline.git
git branch -M main
git push -u origin main
```

### Add the secrets

Repo → Settings → Secrets and variables → Actions:

| Type | Name | Value |
|---|---|---|
| Secret | `DATABASE_URL` | Your full connection string |
| Variable | `LATITUDE` | `-6.2088` |
| Variable | `LONGITUDE` | `106.8456` |

### Test the cron by hand

Actions tab → "Hourly ingest and forecast" → **Run workflow**.

**Checkpoint** — the run goes green and 24 new rows appear in `forecasts`.

This is the moment the pipeline stops needing you. From here it runs hourly
on its own.

Note: the deploy workflow will fail until Part 9. Ignore it for now.

---

## Part 8 · Docker  (45 min)

```bash
docker build -t pm25 .
docker run -p 8080:8080 --env-file .env pm25
```

Open http://localhost:8080/docs

**Checkpoint** — the same four endpoints work inside the container.

If the build fails on `COPY models/`, you skipped Part 3 and have no model
artifact. Go back and train.

---

## Part 9 · Cloud Run  (2 hours, budget more)

This is the hardest part. Not conceptually, just administratively.

1. Create a Google Cloud project at console.cloud.google.com
2. Enable billing (card required, you will not be charged at this volume)
3. Enable the Cloud Run and Cloud Build APIs
4. `gcloud auth login` then `gcloud config set project YOUR_PROJECT_ID`

```bash
gcloud run deploy pm25-forecast \
  --source . \
  --region asia-southeast2 \
  --allow-unauthenticated \
  --memory 1Gi \
  --set-env-vars "DATABASE_URL=your-connection-string"
```

**Checkpoint** — gcloud prints a URL. Open `URL/docs` and it works.

**You now have a public link.** This is the deliverable.

### If IAM defeats you

Give it 90 minutes, no more. Then either:

- Store a service account JSON key as a GitHub secret instead of using
  Workload Identity Federation. Less correct, works immediately.
- Or switch to Render. Free tier cold starts take about 47 seconds, which is
  bad but not fatal. Write the tradeoff in your README and it reads as a
  decision rather than a shortcoming.

A slow live URL beats no URL. Do not spend your whole week here.

---

## Part 10 · Deploy on push  (45 min)

Set the two remaining GitHub secrets (`WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT`)
following Google's Workload Identity Federation setup, or swap
`.github/workflows/deploy.yml` to use a service account key.

**Checkpoint** — push any commit to `main`, watch Actions build and deploy,
confirm the change is live at your Cloud Run URL.

That loop, push to deploy with no manual step, is the CD in CI/CD.

---

## Part 11 · Publish the dashboard  (30 min)

1. share.streamlit.io, sign in with GitHub
2. New app → your repo → `dashboard/app.py`
3. Advanced settings → Secrets, paste:

```toml
DATABASE_URL = "postgresql+psycopg://..."
```

**Checkpoint** — public dashboard URL, block 1 showing live timestamps.

---

## Part 12 · Finish the README  (45 min)

The highest value per hour in the whole project. Add:

- Both live URLs at the very top
- Architecture diagram
- The `/docs` screenshot from Part 5
- What you skipped and why
- Next steps

---

## Order of value, if you run out of time

1. **Parts 1 to 4.** Data flowing, model trained, forecasts logged. Without
   this there is no project.
2. **Part 7.** The cron. This is what makes it run without you.
3. **Part 9.** The public URL.
4. **Part 11.** The dashboard.
5. **Part 12.** The README.
6. Part 10. Deploy on push is the nicest to have and the easiest to cut.

Parts 5, 6, and 8 are local verification. Never skip them, they are fast and
they catch problems while problems are still cheap.

---

## What to do while waiting

The pipeline needs real elapsed time before blocks 3, 4, and 5 have anything
to show. Once Part 7 is running, leave it alone for 48 hours and write your
guiding question answers instead. The dashboard fills itself in.
